// ──────────────────────────────────────────────────────────────────────
// src/hooks/useBurnFxJob.ts — Submit + SSE progress for /burn-fx
// ──────────────────────────────────────────────────────────────────────
//
// Mirror of useSlurmifyJob but for the FX burn-down operation.  Same
// SSE-progress pattern (the backend routes both /slurmify and /burn-fx
// jobs through the same /jobs/{id}/progress endpoint).
//
// Burn flow:
//   1. User has a slurm output (or any source — burn works on
//      anything we have a file_id for).
//   2. They twist the FX knobs and like what they hear via the live
//      Web Audio preview.
//   3. They click "Burn FX" — this hook POSTs the current fxStore
//      params + the source file_id, gets a job_id, subscribes to SSE.
//   4. On done, the resulting burned-FX file_id is written to
//      fxStore.burnedFileId; the OUTPUT player swaps to it.
//
// Source selection — when called with no explicit file_id, the hook
// uses (in priority order):
//   1. slurmStore.output.output_id  — the latest slurm result
//   2. slurmStore.sourceFile.file_id — the raw upload (rare; the user
//      hasn't slurmified yet but wants FX on the source)
// Burning over the burned result (stacking) is NOT supported here —
// each burn starts from the same dry source, and stacking effects
// would require re-uploading the burned file to the backend (which
// /burn-fx already does internally via register_file on the output).
// ──────────────────────────────────────────────────────────────────────

import { useCallback, useRef } from "react"
import { getBackendUrl } from "@/lib/api"
import { useFxStore, type FxParams } from "@/stores/fxStore"
import { useSlurmStore } from "@/stores/slurmStore"
import { noteToMs } from "@/lib/note-mode"

/** Convert a fxStore rate field (with optional note-mode) to Hz before
 *  sending to the Python /burn-fx endpoint.  Today the Python schema
 *  accepts only numeric Hz values — the note ↔ Hz logic lives entirely
 *  on the JS side.  See PLAN_FX_RACK_V0.3.md §3.2 for the rationale.
 *
 *  In Hz mode the value is passed through unchanged.  In ♪ mode we
 *  resolve note→Hz at the currently-detected BPM (slurmify analysis
 *  result, or 120 fallback if no slurm has been run yet).  The same
 *  formula `1000 / noteToMs(note, bpm)` matches what useFxChain.ts
 *  does for live preview, so burned output is sample-accurate to what
 *  the user just heard. */
function resolveRateHz(
  rate: number,
  mode: "Hz" | "♪",
  note: string,
  bpm: number,
): number {
  if (mode !== "♪") return rate
  const ms = noteToMs(note, bpm)
  return ms > 0 ? 1000 / ms : rate
}

/** Build the JSON body for POST /burn-fx.  Mirrors BurnFxRequest in
 *  src-python/api/fx.py — note the camel→snake mapping. */
function buildRequestBody(
  fileId: string,
  fx: FxParams,
  outputFormat: string,
  effectiveBpm: number,
): Record<string, unknown> {
  // Pre-resolve any note-mode rates/times to numeric values before
  // serialising.  The Python burn-fx endpoint accepts only plain
  // Hz / seconds; keeping the note grammar JS-side avoids duplicating
  // the note parser in Python's fx.py.
  const phaseRateHz = resolveRateHz(
    fx.phaseRate, fx.phaseRateMode, fx.phaseRateNote, effectiveBpm,
  )
  const tremoloRateHz = resolveRateHz(
    fx.tremoloRate, fx.tremoloRateMode, fx.tremoloRateNote, effectiveBpm,
  )
  const pannerSweepRateHz = resolveRateHz(
    fx.pannerSweepRate, fx.pannerSweepRateMode, fx.pannerSweepRateNote, effectiveBpm,
  )
  // Delay is in SECONDS in fxStore (range 0–2).  In ms-mode we pass
  // fx.delayTime through; in ♪-mode we resolve note→ms then divide
  // by 1000.  Pre-v0.3 this conversion was skipped — burn-fx silently
  // used the stale fx.delayTime from before the user switched to
  // ♪-mode, so burned delay didn't match the live preview.
  let delaySec = fx.delayTime
  if (fx.delayTimeMode === "♪") {
    const ms = noteToMs(fx.delayTimeNote, effectiveBpm)
    if (ms > 0) delaySec = ms / 1000
  }
  // Per-effect enable gates.  Even though the rack visually disables a
  // bypassed effect's knobs, fxStore still holds the last knob values
  // — Python doesn't need to know about the enable flag (depth=0 or
  // mix=0 is functionally bypass for every effect in the chain), but
  // we explicitly zero them here so the burned output exactly matches
  // the live preview when the user has clicked the rack header to
  // disable an effect.
  const tremoloDepth = fx.tremoloEnabled ? fx.tremoloDepth : 0
  const pannerMix    = fx.pannerEnabled  ? fx.pannerMix    : 0
  return {
    file_id:       fileId,
    dist_drive:    fx.distEnabled    ? fx.distDrive   : 0,
    ring_freq:     fx.ringFreq,
    ring_depth:    fx.ringEnabled    ? fx.ringDepth   : 0,
    delay_sec:     delaySec,
    delay_fb:      fx.delayFb,
    delay_mix:     fx.delayEnabled   ? fx.delayMix    : 0,
    phase_rate:    phaseRateHz,
    phase_depth:   fx.phaserEnabled  ? fx.phaseDepth  : 0,
    // ── v0.3 additions (FE/BE parity) ──────────────────────────────
    tremolo_rate:      tremoloRateHz,
    tremolo_depth:     tremoloDepth,
    tremolo_phase:     fx.tremoloPhase,
    panner_sweep_rate: pannerSweepRateHz,
    panner_spread_l:   fx.pannerSpreadL,
    panner_spread_r:   fx.pannerSpreadR,
    panner_wave:       fx.pannerSweepWave,
    panner_mix:        pannerMix,
    // ── v0.3 Phase 3: reverb (Freeverb) ──────────────────────────
    reverb_size:       fx.reverbSize,
    reverb_decay:      fx.reverbDecay,
    reverb_mix:        fx.reverbEnabled ? fx.reverbMix : 0,
    // ── v0.3 Phase 4: pitch shifter (pyrubberband on burn) ───────
    // Combine semitones + cents into one float before sending so
    // the Python schema can stay simple (one combined value, no
    // separate cents field).  e.g. semitones=-1, cents=-50
    // → -1.5 semitones effective.  When disabled, force 0 so the
    // _fx_pitch early-exit fires without invoking pyrubberband.
    pitch_semitones:   fx.pitchEnabled
                         ? fx.pitchSemitones + fx.pitchCents / 100
                         : 0,
    pitch_mix:         fx.pitchEnabled ? fx.pitchMix : 0,
    output_format: outputFormat,
  }
}

interface BurnFxJobApi {
  /** Kick off a burn-fx run.  If `sourceFileId` is omitted, the hook
   *  picks the slurm output or raw source automatically.
   *
   *  Returns the burned-FX file_id on success, or `null` on failure.
   *  This lets other flows (e.g., useRenderVideoJob's auto-burn-then-
   *  render path introduced for the "FX-on-by-default for YouTube"
   *  UX change) await the burn to completion and use its output
   *  directly without watching the fxStore for `burnedFileId` to
   *  populate.  fxStore is still updated as a side-effect (so the
   *  OUTPUT module's player swaps to the burned file as before). */
  run:    (sourceFileId?: string) => Promise<string | null>
  cancel: () => void
}

export function useBurnFxJob(): BurnFxJobApi {
  const eventSourceRef = useRef<EventSource | null>(null)

  const startBurn  = useFxStore((s) => s.startBurn)
  const updateBurn = useFxStore((s) => s.updateBurn)
  const finishBurn = useFxStore((s) => s.finishBurn)

  const cancel = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const run = useCallback(async (sourceFileId?: string): Promise<string | null> => {
    // Resolve which file_id to burn FX onto.  Priority: explicit arg
    // → slurm output → raw source.
    const slurm = useSlurmStore.getState()
    const fxState = useFxStore.getState()
    const fileId =
      sourceFileId ??
      slurm.output?.output_id ??
      slurm.sourceFile?.file_id

    if (!fileId) {
      finishBurn(null, "no source file to burn FX onto")
      return null
    }

    // Abort any previous in-flight burn before starting a new one.
    cancel()

    // Effective BPM for any note-mode FX rate conversions.  Same
    // priority logic useEffectiveBpm() encapsulates (override →
    // detected → 120 fallback), inlined here because we're inside a
    // callback, not a hook.  See useEffectiveBpm.ts for the canonical
    // version and ADR-0020 for the source-of-truth contract.
    const bpmOverride = slurm.params.bpm_override
    const detectedBpm = slurm.analysis?.bpm
    const effectiveBpm =
        bpmOverride && bpmOverride > 0  ? bpmOverride
      : detectedBpm && detectedBpm > 0  ? detectedBpm
      :                                   120

    try {
      const baseUrl = await getBackendUrl()

      const res = await fetch(`${baseUrl}/burn-fx`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(buildRequestBody(
          fileId,
          fxState.params,
          slurm.params.output_format,
          effectiveBpm,
        )),
      })
      if (!res.ok) {
        const body = await res.text().catch(() => "")
        throw new Error(`/burn-fx ${res.status}: ${body}`)
      }
      const { job_id } = (await res.json()) as { job_id: string }
      startBurn(job_id)

      // Subscribe to the same SSE stream /slurmify uses.  Server-side
      // jobs.py is shared between the two endpoints.
      const es = new EventSource(`${baseUrl}/jobs/${job_id}/progress`)
      eventSourceRef.current = es

      // Wrap the SSE consumer in a Promise so the caller can `await`
      // the final outcome and receive the burned file_id (or null on
      // failure).  Resolves exactly once — either when the SSE
      // payload's `done=true` arrives, or when the connection drops.
      return await new Promise<string | null>((resolve) => {
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
            updateBurn({ progress: payload.progress, desc: payload.desc })
            if (payload.done) {
              es.close()
              eventSourceRef.current = null
              if (payload.error) {
                finishBurn(null, payload.error)
                resolve(null)
              } else if (payload.output_id) {
                finishBurn(payload.output_id, null)
                resolve(payload.output_id)
              } else {
                finishBurn(null, "burn-fx finished without an output_id")
                resolve(null)
              }
            }
          } catch (e) {
            es.close()
            eventSourceRef.current = null
            finishBurn(null, `bad SSE payload: ${(e as Error).message}`)
            resolve(null)
          }
        }

        es.onerror = () => {
          if (eventSourceRef.current === es) {
            es.close()
            eventSourceRef.current = null
            finishBurn(null, "SSE connection lost during burn-fx")
            resolve(null)
          }
        }
      })
    } catch (e) {
      finishBurn(null, (e as Error).message ?? "unknown error")
      return null
    }
  }, [cancel, startBurn, updateBurn, finishBurn])

  return { run, cancel }
}
