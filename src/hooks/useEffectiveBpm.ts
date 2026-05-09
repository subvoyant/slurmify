// ──────────────────────────────────────────────────────────────────────
// src/hooks/useEffectiveBpm.ts — Single source of truth for "what BPM
// should the live ♪ ⇄ ms hint use right now?"
// ──────────────────────────────────────────────────────────────────────
//
// Priority (matches v0.1.6's `_slurmGetBpm` plus the v0.2.0 /analyze
// auto-detect addition):
//
//   1. params.bpm_override         — user explicitly typed a value
//   2. analysis.bpm                — librosa auto-detection (Phase E3c.1.5)
//   3. 120                         — fallback (matches DEFAULT_BPM in
//                                    slurmcore.py)
//
// The returned object also exposes the "source" so the UI can label the
// hint truthfully ("@ 126 BPM (detected)" vs "@ 140 BPM (override)" vs
// "@ 120 BPM (fallback)").  Without this distinction the user can't
// tell whether their override was ignored, or whether librosa even
// finished analyzing.
//
// Note that the slurmify backend ignores this hook entirely — it
// computes its own effective BPM from `detect_slice_points` (per
// ADR-0020).  This hook is for FRONTEND DISPLAY ONLY.
// ──────────────────────────────────────────────────────────────────────

import { useSlurmStore } from "@/stores/slurmStore"

export type BpmSource = "override" | "detected" | "fallback"

export interface EffectiveBpm {
  /** The BPM to use for ♪ ⇄ ms conversions in the UI right now. */
  bpm: number
  /** Where the BPM came from — drives the human-readable hint label. */
  source: BpmSource
  /** True if analysis is still in flight (no /analyze response yet). */
  detecting: boolean
}

/** v0.1.6 used 120 as the silent fallback when no override was set
 *  and librosa hadn't been run yet.  We keep the same default so
 *  legacy projects feel identical. */
const DEFAULT_BPM = 120

export function useEffectiveBpm(): EffectiveBpm {
  const override  = useSlurmStore((s) => s.params.bpm_override)
  const analysis  = useSlurmStore((s) => s.analysis)

  // Override wins outright — even if librosa disagrees, the user told
  // us what they want and the backend will honor it via bpm_override.
  if (override !== null && override > 0) {
    return { bpm: override, source: "override", detecting: false }
  }

  // analysis === null means /analyze hasn't completed yet (or never
  // fired — e.g., backend offline).  Fall back to the default but
  // surface the "detecting" flag so the hint can show "(detecting…)".
  if (analysis === null) {
    return { bpm: DEFAULT_BPM, source: "fallback", detecting: true }
  }

  // analysis present but bpm could still be null (silence, very short
  // file, librosa exception).  Treat that as "fallback known" — not
  // detecting anymore, but no estimate available.
  if (analysis.bpm === null || analysis.bpm <= 0) {
    return { bpm: DEFAULT_BPM, source: "fallback", detecting: false }
  }

  return { bpm: analysis.bpm, source: "detected", detecting: false }
}
