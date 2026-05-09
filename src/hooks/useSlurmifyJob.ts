// ──────────────────────────────────────────────────────────────────────
// src/hooks/useSlurmifyJob.ts — Submit + SSE progress for /slurmify
// ──────────────────────────────────────────────────────────────────────
//
// Owns the full slurmify lifecycle on the frontend:
//
//   1. Build the request body from the slurmStore params + source
//      file_id.
//   2. POST to /slurmify, get back a job_id.
//   3. Open an EventSource on /jobs/{id}/progress.
//   4. On every SSE message, update the store's progress + desc.
//   5. On done, set the output file URL in the store.
//   6. On error, set the store's error field.
//
// Returns a single { run, cancel } pair; consumers (the OUTPUT
// module's Slurmify button) call `run()` and rely on the store for
// progress display.  Multiple calls to run() abort any in-flight job
// before starting a new one — the user pressing Slurmify again
// "supersedes" the previous run rather than queueing.
// ──────────────────────────────────────────────────────────────────────

import { useCallback, useRef } from "react"
import { useSlurmStore, type SlurmParams } from "@/stores/slurmStore"
import { getBackendUrl } from "@/lib/api"

/**
 * Build the JSON body for POST /slurmify.  Mirrors the SlurmifyRequest
 * Pydantic model in src-python/api/slurmify.py.
 *
 * Critical mapping nuances:
 *   • Note-mode params: only send the *_note when the corresponding
 *     mode is "♪".  When mode is "ms", send empty string so the
 *     backend uses the *_ms slider value (matches v0.1.6 semantics —
 *     ADR-0020).
 *   • bpm_override: null vs number.  Empty textbox → null.
 *   • beat_mask: null when all-true (zero overhead in slurmify).
 */
function buildRequestBody(fileId: string, params: SlurmParams): Record<string, unknown> {
  return {
    file_id:                fileId,
    speed:                  params.speed,
    resolution:             params.resolution,
    transient_sensitivity:  params.transient_sensitivity,
    envelope_ms:            params.envelope_ms,
    preserve_pitch:         params.preserve_pitch,
    pitch_shift_semitones:  params.pitch_shift_semitones,
    randomize_order:        params.randomize_order,
    reverse_chance:         params.reverse_chance,
    stutter_chance:         params.stutter_chance,
    stutter_skip_ms:        params.stutter_skip_ms,
    stutter_max_reps:       params.stutter_max_reps,
    stutter_spread:         params.stutter_spread,
    beat_trim_start_ms:     params.beat_trim_start_ms,
    beat_trim_end_ms:       params.beat_trim_end_ms,
    beat_gap_ms:            params.beat_gap_ms,
    bpm_override:           params.bpm_override,
    start_sec:              params.start_sec,
    end_sec:                params.end_sec,
    seed:                   params.seed,
    beat_mask:              params.beat_mask && params.beat_mask.some((v) => !v)
                              ? params.beat_mask
                              : null,
    output_format:          params.output_format,

    // Note-mode plumbing (ADR-0020).  Only send the note string when
    // the corresponding mode is "♪"; otherwise empty so the backend
    // falls through to the _ms value.
    stutter_skip_note:      params.stutter_skip_mode    === "♪" ? params.stutter_skip_note    : "",
    beat_trim_start_note:   params.beat_trim_start_mode === "♪" ? params.beat_trim_start_note : "",
    beat_trim_end_note:     params.beat_trim_end_mode   === "♪" ? params.beat_trim_end_note   : "",
    beat_gap_note:          params.beat_gap_mode        === "♪" ? params.beat_gap_note        : "",
  }
}

interface SlurmifyJobApi {
  /** Kick off a new slurmify run.  Aborts any in-flight job first.
   *  Resolves when the job completes (success OR error) — useful for
   *  scripted flows; the store carries everything UI needs. */
  run: () => Promise<void>
  /** Abort the in-flight job (closes SSE, clears store running state). */
  cancel: () => void
}

export function useSlurmifyJob(): SlurmifyJobApi {
  const eventSourceRef = useRef<EventSource | null>(null)

  // Store hooks — read in run() rather than at hook-call time so the
  // run() closure always sees the LATEST params (Zustand's getState()
  // returns the live store snapshot).
  const startJob  = useSlurmStore((s) => s.startJob)
  const updateJob = useSlurmStore((s) => s.updateJob)
  const finishJob = useSlurmStore((s) => s.finishJob)
  const setOutput = useSlurmStore((s) => s.setOutput)

  const cancel = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const run = useCallback(async () => {
    // Pull latest store snapshot (NOT the values captured at hook
    // mount).  Zustand's getState() is the escape hatch for this.
    const { sourceFile, params } = useSlurmStore.getState()
    if (!sourceFile) {
      finishJob(null, "no source file loaded")
      return
    }

    // Abort any previous in-flight job before starting a new one.
    cancel()

    try {
      const baseUrl = await getBackendUrl()

      // ── Step 1: POST /slurmify, get a job_id ─────────────────────
      const res = await fetch(`${baseUrl}/slurmify`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(buildRequestBody(sourceFile.file_id, params)),
      })
      if (!res.ok) {
        const body = await res.text().catch(() => "")
        throw new Error(`/slurmify ${res.status}: ${body}`)
      }
      const { job_id } = (await res.json()) as { job_id: string }
      startJob(job_id)

      // ── Step 2: Subscribe to SSE progress stream ────────────────
      const es = new EventSource(`${baseUrl}/jobs/${job_id}/progress`)
      eventSourceRef.current = es

      // SSE messages each carry the full Job snapshot from the
      // backend (see jobs.py to_dict()).  We update the store on
      // every message; the UI re-renders the progress bar.
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
          updateJob({ progress: payload.progress, desc: payload.desc })
          if (payload.done) {
            es.close()
            eventSourceRef.current = null
            if (payload.error) {
              finishJob(null, payload.error)
            } else if (payload.output_id) {
              const url = `${baseUrl}/files/${payload.output_id}`
              setOutput({ output_id: payload.output_id, url })
              finishJob({ output_id: payload.output_id, url }, null)
            } else {
              finishJob(null, "job finished without an output_id")
            }
          }
        } catch (e) {
          // Malformed SSE payload — surface as an error and close.
          es.close()
          eventSourceRef.current = null
          finishJob(null, `bad SSE payload: ${(e as Error).message}`)
        }
      }

      // SSE error fires when the connection is closed unexpectedly
      // (backend died, network blip, etc.).  Treat as a job failure
      // unless we already received the `done: true` payload (in
      // which case eventSourceRef has been nulled and we ignore).
      es.onerror = () => {
        if (eventSourceRef.current === es) {
          es.close()
          eventSourceRef.current = null
          finishJob(null, "SSE connection lost")
        }
      }
    } catch (e) {
      finishJob(null, (e as Error).message ?? "unknown error")
    }
  }, [cancel, startJob, updateJob, finishJob, setOutput])

  return { run, cancel }
}
