// ──────────────────────────────────────────────────────────────────────
// src/lib/note-mode.ts — musical-note ⇄ milliseconds conversion helpers
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of slurmcore.py's `_note_to_ms` and ui_assets.py's
// `_slurmNoteToMs` (v0.1.6 INIT_JS).  These two implementations MUST
// produce the same numbers — see ADR-0020 for the design rationale and
// CLAUDE.md "Danger zones #13" for the maintenance rule.
//
// The frontend uses these helpers for two purposes only:
//
//   1. Live ms-equivalent hint under each musical knob when in ♪ mode
//      ("≈ 119 ms @ 126 BPM").  Display-only — slurmcore is the source
//      of truth for what actually gets baked into the audio.
//
//   2. Reverse-direction "≈ 1/N" hint when in ms mode — finds the
//      closest labelled note to the current ms value at the current
//      BPM.  Also display-only.
//
// Grammar (from ADR-0020):
//   "1/N"     whole-note fraction (1/4 = quarter note = 1 beat at 4/4)
//   "1/N."    dotted variant — value × 1.5
//   "1/NT"    triplet variant — value × 2/3
//   "1" / "2" whole-note multiples (1 = 4 beats; 2 = 8 beats)
//
// Returns 0 for invalid input or non-positive BPM so callers can use
// the result directly with `if (ms > 0)` guards.
// ──────────────────────────────────────────────────────────────────────

/**
 * The labelled note values in ascending duration order.  Sources of
 * truth for:
 *   • the Select dropdown shown when a knob is in ♪ mode
 *   • the closest-note search used by the reverse-direction hint
 *
 * Order matters for the dropdown display (shortest first, longest
 * last) but not for the closest-note search (we iterate all of them).
 *
 * Kept in sync with `_SLURM_NOTE_LABELS` in ui_assets.py.
 */
export const NOTE_LABELS = [
  "1/64",
  "1/32",
  "1/16T", "1/16", "1/16.",
  "1/8T",  "1/8",  "1/8.",
  "1/4T",  "1/4",  "1/4.",
  "1/2",
  "1",
  "2",
] as const

export type NoteLabel = typeof NOTE_LABELS[number]

/**
 * Convert a musical note fraction string to milliseconds at the given
 * BPM.  Returns 0 for null/empty/unparseable input or non-positive BPM
 * so callers can use the result directly.
 *
 * IMPORTANT — this MUST match `_note_to_ms` in slurmcore.py exactly.
 * Both implementations are tested against the same expected values:
 *
 *   bpm=120: "1/4" → 500   "1/8" → 250   "1/16" → 125
 *            "1/8." → 375  "1/8T" → 166.667  "1" → 2000  "2" → 4000
 *
 * Change the grammar in one → change in the other in the same commit.
 */
export function noteToMs(note: string | null | undefined, bpm: number): number {
  if (!note || typeof note !== "string") return 0
  if (!Number.isFinite(bpm) || bpm <= 0) return 0

  let s = note.trim()
  if (!s || s.toLowerCase() === "off") return 0

  // Strip the optional dotted/triplet suffix.  Compound forms like
  // "1/8T." are not supported — they're musically ambiguous and
  // slurmcore.py rejects them too.
  let dotted  = false
  let triplet = false
  if (s.endsWith(".")) {
    dotted = true
    s = s.slice(0, -1)
  } else if (s.endsWith("T")) {
    triplet = true
    s = s.slice(0, -1)
  }

  // Parse "1/N" as a fraction; bare integers parse as whole-note multiples.
  let value: number
  if (s.includes("/")) {
    const [numStr, denStr] = s.split("/", 2)
    const num = parseFloat(numStr)
    const den = parseFloat(denStr)
    if (!Number.isFinite(num) || !Number.isFinite(den) || den === 0) return 0
    value = num / den
  } else {
    value = parseFloat(s)
    if (!Number.isFinite(value)) return 0
  }

  // Convert whole-note units → beats (4 beats per whole note in 4/4)
  // → ms via the BPM.  Apply dotted/triplet multiplier on the way.
  let beats = value * 4.0
  if (dotted)       beats *= 1.5
  else if (triplet) beats *= 2.0 / 3.0

  return beats * (60_000.0 / bpm)
}

/**
 * Reverse direction: find the labelled note whose ms value at this BPM
 * is closest to the supplied ms value.  Used for the "≈ 1/N" hint
 * shown when a knob is in ms mode.  Returns "" for non-positive ms or
 * non-positive BPM.
 *
 * Kept in sync with `_slurmMsToClosestNote` in ui_assets.py.
 */
export function msToClosestNote(ms: number, bpm: number): NoteLabel | "" {
  if (!Number.isFinite(ms) || ms <= 0) return ""
  if (!Number.isFinite(bpm) || bpm <= 0) return ""

  let bestNote: NoteLabel | "" = ""
  let bestDelta = Infinity
  for (const note of NOTE_LABELS) {
    const noteMs = noteToMs(note, bpm)
    if (noteMs <= 0) continue
    const delta = Math.abs(noteMs - ms)
    if (delta < bestDelta) {
      bestDelta = delta
      bestNote  = note
    }
  }
  return bestNote
}

/**
 * Format a millisecond duration the way the v0.1.6 hints did:
 *   • ≥ 10 ms → 0 decimal places ("125 ms")
 *   • < 10 ms → 1 decimal place ("8.5 ms")
 *
 * Kept consistent with the formatting branch inside
 * `_slurmUpdateHint` in ui_assets.py so the new and old hints look
 * identical.
 */
export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0"
  return ms >= 10 ? ms.toFixed(0) : ms.toFixed(1)
}
