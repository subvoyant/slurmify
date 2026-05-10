// ──────────────────────────────────────────────────────────────────────
// src/hooks/useRenderVideoJob.ts — Submit + SSE for /render-video
// ──────────────────────────────────────────────────────────────────────
//
// Same job-and-SSE pattern as useSlurmifyJob and useBurnFxJob; the
// backend routes all three through /jobs/{id}/progress.  Difference:
// this hook builds a much fatter request body — every slurmify and FX
// param is forwarded so the backend can bake them into the MP4's
// description metadata atom (PATCH= JSON blob, ADR-0008).
//
// Source-of-audio resolution:
//   1. burnedFileId from fxStore        — preferred (FX baked in)
//   2. slurmStore.output.output_id      — bare slurm output
//   3. slurmStore.sourceFile.file_id    — last-resort raw upload
// The rest of the params come straight off slurmStore.params and
// fxStore.params; if the user has the FX knobs at zero AND no burn,
// the rendered video is just the dry slurm.
// ──────────────────────────────────────────────────────────────────────

import { useCallback, useRef } from "react"
import { getBackendUrl } from "@/lib/api"
import { useVideoStore } from "@/stores/videoStore"
import { useSlurmStore, type SlurmParams } from "@/stores/slurmStore"
import { useFxStore, type FxParams } from "@/stores/fxStore"
import type { VideoMetadata } from "@/stores/videoStore"
import { useBurnFxJob } from "@/hooks/useBurnFxJob"

interface RenderRequestPaths {
  audioFileId:       string
  audioSourceLabel:  string   // human-readable for PATCH metadata
  srcInputFileId:    string | null
}

/** Build the JSON body for POST /render-video.  Mirrors
 *  RenderVideoRequest in src-python/api/render.py field-by-field. */
function buildRequestBody(
  paths:    RenderRequestPaths,
  meta:     VideoMetadata,
  params:   SlurmParams,
  fx:       FxParams,
): Record<string, unknown> {
  return {
    audio_file_id:        paths.audioFileId,
    audio_source_label:   paths.audioSourceLabel,
    src_input_file_id:    paths.srcInputFileId,
    include_source_filename: meta.includeSourceFilename,

    title_text:           meta.title,
    creator_text:         meta.creator,

    // Slurmify core params (all forwarded for PATCH metadata)
    speed:                 params.speed,
    resolution:            params.resolution,
    transient_sensitivity: params.transient_sensitivity,
    envelope_ms:           params.envelope_ms,
    preserve_pitch:        params.preserve_pitch,
    pitch_shift_semitones: params.pitch_shift_semitones,
    randomize_order:       params.randomize_order,
    reverse_chance:        params.reverse_chance,
    stutter_chance:        params.stutter_chance,
    stutter_skip_ms:       params.stutter_skip_ms,
    stutter_max_reps:      params.stutter_max_reps,
    stutter_spread:        params.stutter_spread,
    beat_trim_start_ms:    params.beat_trim_start_ms,
    beat_trim_end_ms:      params.beat_trim_end_ms,
    beat_gap_ms:           params.beat_gap_ms,
    bpm_override:          params.bpm_override,
    seed:                  params.seed,
    beat_mask:             params.beat_mask,

    // Note-mode (mode, note) pairs — only meaningful when mode is "♪"
    // but harmless to forward unconditionally; backend filters.
    stutter_skip_mode:     params.stutter_skip_mode,
    stutter_skip_note:     params.stutter_skip_note,
    beat_trim_start_mode:  params.beat_trim_start_mode,
    beat_trim_start_note:  params.beat_trim_start_note,
    beat_trim_end_mode:    params.beat_trim_end_mode,
    beat_trim_end_note:    params.beat_trim_end_note,
    beat_gap_mode:         params.beat_gap_mode,
    beat_gap_note:         params.beat_gap_note,

    // FX params (also baked into PATCH)
    dist_drive:  fx.distDrive,
    ring_freq:   fx.ringFreq,
    ring_depth:  fx.ringDepth,
    delay_time:  fx.delayTime,
    delay_fb:    fx.delayFb,
    delay_mix:   fx.delayMix,
    phase_rate:  fx.phaseRate,
    phase_depth: fx.phaseDepth,
  }
}

interface RenderVideoJobApi {
  run: () => Promise<void>
  cancel: () => void
}

export function useRenderVideoJob(): RenderVideoJobApi {
  const eventSourceRef = useRef<EventSource | null>(null)

  const startRender  = useVideoStore((s) => s.startRender)
  const updateRender = useVideoStore((s) => s.updateRender)
  const finishRender = useVideoStore((s) => s.finishRender)

  // We may need to auto-burn FX before rendering (the new default —
  // see below).  useBurnFxJob.run returns the burned file_id (or null)
  // so we can chain directly without watching fxStore for state changes.
  const { run: burnRun } = useBurnFxJob()

  const cancel = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const run = useCallback(async () => {
    const slurm   = useSlurmStore.getState()
    const fxState = useFxStore.getState()
    const meta    = useVideoStore.getState().metadata

    // Resolve which audio source to encode.  Three modes (see
    // videoStore.ts for the full rationale + history):
    //
    //   "fx-burned" (DEFAULT)
    //     Bake FX into the render.  Reuse `fxState.burnedFileId` if
    //     present; otherwise auto-run /burn-fx first and use the
    //     resulting file_id.  This is the "what users actually
    //     mean when they dial up FX and click render" path.
    //
    //   "slurm"
    //     Explicit dry / no-FX export.  Errors if no slurm output
    //     exists yet (VideoBody handles auto-slurmifying via the
    //     slurmRun() pre-check, so by the time we get here
    //     `slurm.output` should be populated).
    //
    //   "auto" (legacy alias)
    //     Treated as "fx-burned" — same auto-burn-then-render flow.
    //     We keep the type variant so v0.2.0.0 persisted state
    //     doesn't reset to default on upgrade.
    //
    // Fall-through to raw source is only used in the rare case where
    // no slurm output AND no burned FX exist AND a sourceFile is
    // present — render the raw upload as-is.
    const audioSource = meta.audioSource ?? "fx-burned"
    let paths: RenderRequestPaths

    if (audioSource === "slurm") {
      // Explicit dry pick.
      if (!slurm.output) {
        finishRender(null, "no slurm output to render — click slurmify first")
        return
      }
      paths = {
        audioFileId:       slurm.output.output_id,
        audioSourceLabel:  "slurm output",
        srcInputFileId:    slurm.sourceFile?.file_id ?? null,
      }
    } else {
      // "fx-burned" or "auto" (legacy) — both go through the same
      // FX-on path.

      // Step 1: figure out which file to burn FX onto.  Prefer the
      // slurm output (most useful — slurm rhythms + FX), fall back to
      // raw source (the "no slurmify needed, FX over the original"
      // case, rare but valid).
      const burnSourceId =
        slurm.output?.output_id ?? slurm.sourceFile?.file_id ?? null

      if (!burnSourceId) {
        finishRender(
          null,
          "no audio source to render — drop a file or click slurmify first",
        )
        return
      }

      // Step 2: ALWAYS run a fresh /burn-fx pass so the rendered MP4
      // reflects the user's CURRENT FX-knob state rather than whatever
      // was burned at some earlier point in the session.  This is the
      // mental-model match that motivated the W5b "FX-on-by-default"
      // change in the first place: a user who dials up reverb, then
      // clicks render YouTube MP4, expects to hear that reverb in
      // the export — not the FX state from when they last clicked
      // "burn FX" five minutes ago.  The cost is one extra ~5–15 s
      // burn pass; the pre-existing fxStore.burnedFileId still gets
      // refreshed (so the OUTPUT player swaps to the latest burn at
      // the same time).  Users who want to skip the burn entirely can
      // pick "clean slurm (dry)" in the audio selector.
      const burnedFileId = await burnRun(burnSourceId)
      if (!burnedFileId) {
        // burnRun already populated fxStore.error; surface that as
        // the render error too so the user sees ONE message in the
        // VIDEO module instead of having to glance over at FX.
        const burnErr =
          useFxStore.getState().error ?? "auto-burn FX failed"
        finishRender(null, `auto-burn FX before render failed: ${burnErr}`)
        return
      }

      paths = {
        audioFileId:       burnedFileId,
        audioSourceLabel:  "FX-burned output",
        srcInputFileId:    slurm.sourceFile?.file_id ?? null,
      }
    }

    cancel()

    try {
      const baseUrl = await getBackendUrl()
      const res = await fetch(`${baseUrl}/render-video`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(buildRequestBody(paths, meta, slurm.params, fxState.params)),
      })
      if (!res.ok) {
        const body = await res.text().catch(() => "")
        throw new Error(`/render-video ${res.status}: ${body}`)
      }
      const { job_id } = (await res.json()) as { job_id: string }
      startRender(job_id)

      const es = new EventSource(`${baseUrl}/jobs/${job_id}/progress`)
      eventSourceRef.current = es

      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            id:        string
            progress:  number
            desc:      string
            done:      boolean
            output_id: string | null
            error:     string | null
          }
          updateRender({ progress: payload.progress, desc: payload.desc })
          if (payload.done) {
            es.close()
            eventSourceRef.current = null
            if (payload.error) {
              finishRender(null, payload.error)
            } else if (payload.output_id) {
              finishRender(payload.output_id, null)
            } else {
              finishRender(null, "render finished without an output_id")
            }
          }
        } catch (e) {
          es.close()
          eventSourceRef.current = null
          finishRender(null, `bad SSE payload: ${(e as Error).message}`)
        }
      }

      es.onerror = () => {
        if (eventSourceRef.current === es) {
          es.close()
          eventSourceRef.current = null
          finishRender(null, "SSE connection lost during render-video")
        }
      }
    } catch (e) {
      finishRender(null, (e as Error).message ?? "unknown error")
    }
  }, [cancel, startRender, updateRender, finishRender])

  return { run, cancel }
}
