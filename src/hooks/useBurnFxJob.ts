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

/** Build the JSON body for POST /burn-fx.  Mirrors BurnFxRequest in
 *  src-python/api/fx.py — note the camel→snake mapping. */
function buildRequestBody(
  fileId: string,
  fx: FxParams,
  outputFormat: string,
): Record<string, unknown> {
  return {
    file_id:       fileId,
    dist_drive:    fx.distDrive,
    ring_freq:     fx.ringFreq,
    ring_depth:    fx.ringDepth,
    delay_sec:     fx.delayTime,
    delay_fb:      fx.delayFb,
    delay_mix:     fx.delayMix,
    phase_rate:    fx.phaseRate,
    phase_depth:   fx.phaseDepth,
    output_format: outputFormat,
  }
}

interface BurnFxJobApi {
  /** Kick off a burn-fx run.  If `sourceFileId` is omitted, the hook
   *  picks the slurm output or raw source automatically. */
  run:    (sourceFileId?: string) => Promise<void>
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

  const run = useCallback(async (sourceFileId?: string) => {
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
      return
    }

    // Abort any previous in-flight burn before starting a new one.
    cancel()

    try {
      const baseUrl = await getBackendUrl()

      const res = await fetch(`${baseUrl}/burn-fx`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(buildRequestBody(
          fileId,
          fxState.params,
          slurm.params.output_format,
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
            } else if (payload.output_id) {
              finishBurn(payload.output_id, null)
            } else {
              finishBurn(null, "burn-fx finished without an output_id")
            }
          }
        } catch (e) {
          es.close()
          eventSourceRef.current = null
          finishBurn(null, `bad SSE payload: ${(e as Error).message}`)
        }
      }

      es.onerror = () => {
        if (eventSourceRef.current === es) {
          es.close()
          eventSourceRef.current = null
          finishBurn(null, "SSE connection lost during burn-fx")
        }
      }
    } catch (e) {
      finishBurn(null, (e as Error).message ?? "unknown error")
    }
  }, [cancel, startBurn, updateBurn, finishBurn])

  return { run, cancel }
}
