// ──────────────────────────────────────────────────────────────────────
// src/components/ResolutionPicker.tsx — Chip-row picker for slice resolution
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's resolution radio (slurm_ui.py build_ui()).
// Chip row of nine values: 1/1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64, 1/128,
// MAX RANDOM.  Selected chip lights up in --primary; others stay
// muted.
//
// Why custom chips and not Radix RadioGroup?
//   The chip aesthetic doesn't quite fit Radix's RadioGroup (which
//   wants a list of radio inputs each in its own item).  Custom
//   <button> chips are 30 lines, fully accessible (each is a real
//   <button> with type="button"), and let us style every state
//   precisely — selected, hover, focus.
//
// MAX RANDOM gets special visual treatment in v0.1.6 (a red-orange
// hover gif, etc.).  v0.2.0 keeps it functionally distinct via a
// brighter accent border; the easter-egg gif comes back in W5 polish.
//
// Auto-shuffle behavior (ADR-0013): selecting MAX RANDOM should
// auto-check the randomize_order flag.  We DO NOT internalize that
// here — the parent owns both fields and applies the rule on change.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { EasterEggHover } from "@/components/EasterEggHover"

// ── Easter-egg gif import ─────────────────────────────────────────────
// Max the tester slides in from the right of the MAX RANDOM chip on
// hover (110×149, matches v0.1.6 sizing).  Vite hashes + bundles.
import maxGif from "../../graphic/max.gif"

export const RESOLUTION_OPTIONS = [
  "1/1",
  "1/2",
  "1/4",
  "1/8",
  "1/16",
  "1/32",
  "1/64",
  "1/128",
  "MAX RANDOM",
] as const

export type Resolution = typeof RESOLUTION_OPTIONS[number]

/** Per-resolution tooltip text — explains the musical meaning and
 *  typical character of each slice resolution.  All-uppercase chips
 *  read like commands; this longer-form text gives the user context. */
const RESOLUTION_DESCRIPTIONS: Record<Resolution, string> = {
  "1/1":         "Whole-note slices — one slice every 4 beats. Slowest, most spacious chops.",
  "1/2":         "Half-note slices — one slice every 2 beats. Wide, hymn-like phrasing.",
  "1/4":         "Quarter-note slices — one slice per beat. The most musical default.",
  "1/8":         "Eighth-note slices — two slices per beat. Tight rhythmic chop.",
  "1/16":        "Sixteenth-note slices — four per beat. Default. Classic slurm tempo.",
  "1/32":        "32nd-note slices — eight per beat. Edges into glitch territory.",
  "1/64":        "64th-note slices — sixteen per beat. Granular / glitch.",
  "1/128":       "128th-note slices — thirty-two per beat. Extreme micro-chop / audio-rate.",
  "MAX RANDOM":  "Bypasses the beat grid entirely. Slice durations are drawn from a trimodal distribution: stutter (5–30ms), chop (100–500ms), held (1–4s) — chosen 1/3 each. Auto-checks shuffle.",
}

export interface ResolutionPickerProps {
  value:    Resolution
  onChange: (r: Resolution) => void
  disabled?: boolean
}

export function ResolutionPicker({
  value,
  onChange,
  disabled,
}: ResolutionPickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="slice resolution"
      className={cn(
        "flex flex-wrap gap-1",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      {RESOLUTION_OPTIONS.map((opt) => {
        const selected = opt === value
        const isMaxRandom = opt === "MAX RANDOM"
        const chip = (
          <Tip key={opt} text={RESOLUTION_DESCRIPTIONS[opt]}>
            <button
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(opt)}
              className={cn(
                // Base chip: tight, monospace, even sizing.  MAX RANDOM
                // gets extra horizontal padding because its label is
                // wider than the fraction chips.
                "select-none rounded border text-[11px] font-mono",
                "transition-colors",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                isMaxRandom ? "h-7 px-2.5" : "h-7 w-12",
                isMaxRandom && "tracking-[0.05em]",

                // State:
                selected
                  ? cn(
                      "border-primary bg-primary/10 text-primary",
                      "shadow-[0_0_4px_hsl(var(--primary)/0.5)]",
                    )
                  : cn(
                      "border-slurm-border-2 bg-slurm-surface text-slurm-muted",
                      "hover:border-slurm-cyan/50 hover:text-slurm-fg",
                    ),
              )}
            >
              {opt}
            </button>
          </Tip>
        )
        // MAX RANDOM gets the Max-the-tester easter egg sliding in
        // from the right on hover (matches v0.1.6's CSS Block 2 placement).
        if (isMaxRandom) {
          return (
            <EasterEggHover
              key={opt}
              gifSrc={maxGif}
              width={110}
              height={149}
              anchor="slide-in-right"
              // Portal mode so Max's body isn't clipped by the slicing
              // rack module's overflow:hidden.
              // alignToSelector pins his BOTTOM edge to the BEAT TRIM
              // rack's top edge, so he plants his feet on the BEAT
              // TRIM header bar instead of dangling off the MAX RANDOM
              // chip and getting cropped against the resolution row.
              // Horizontal placement stays trigger-relative (his left
              // edge sits just past the chip's right side) — see the
              // slide-in-right case in computeFixedCoords.
              usePortal
              alignToSelector='section[data-rack-name="beat trim"]'
              alt="Max sliding in"
            >
              {chip}
            </EasterEggHover>
          )
        }
        return chip
      })}
    </div>
  )
}
