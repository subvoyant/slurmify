// ──────────────────────────────────────────────────────────────────────
// src/components/BeatMaskStrip.tsx — Per-bar beat dropout chip row
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's beat mask strip (ADR-0019 + ui_assets.py).
// Shows N toggle chips under the resolution picker — each chip
// represents one beat position within a bar at the active resolution:
//
//   1/1   → 1 chip   (one whole-note "beat")
//   1/2   → 2 chips  (two half notes)
//   1/4   → 4 chips  (the canonical 4 beats per bar)
//   1/8   → 8 chips
//   1/16  → 16 chips
//   1/32+ → hidden  (chip count would be too dense)
//   MAX RANDOM → hidden  (no fixed grid)
//
// Each chip is labeled with a circled-digit glyph ① through ⑯
// (matches v0.1.6 exactly — same Unicode range).  Clicking toggles
// the chip on/off; the full mask is sent to slurmify as a list of
// booleans.  Slice i in the slurm output is kept iff
// `mask[i % N]` is true.
//
// All-true mask is stored as `null` in slurmStore for zero overhead
// in slurmcore (slurmify skips the filter step entirely when the
// mask is None).
//
// Resolution change semantics: parent (SlicingBody) is responsible
// for setting beat_mask back to null whenever resolution changes,
// since the chip count differs and a 4-chip mask doesn't translate
// to 16 chips meaningfully.
// ──────────────────────────────────────────────────────────────────────

import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { EasterEggHover } from "@/components/EasterEggHover"

// ── Easter-egg gif import ─────────────────────────────────────────────
// MaxFire peeks up from BEHIND the beat-mask strip on hover (matches
// v0.1.6 CSS Block 5a placement).  The "peek-up-behind" anchor has
// z-index 0 so the chips sit on top of the gif; only the bottom of
// the gif (Max's head) shows above the strip's top edge.
import maxFireGif from "../../graphic/MaxFire02.gif"

/** Resolutions that show a chip strip, mapped to chip count.
 *  Resolutions not in this map render a "dormant" placeholder
 *  instead of being hidden — keeps the user oriented (the control
 *  always has SOME presence in the UI, even when not interactive). */
export const RESOLUTION_CHIP_COUNT: Record<string, number> = {
  "1/1":  1,
  "1/2":  2,
  "1/4":  4,
  "1/8":  8,
  "1/16": 16,
  "1/32": 32,
}

/** Circled-digit glyphs.  Unicode has these for 1-50 in three blocks;
 *  we use them for the first 20 (most common) and fall back to plain
 *  digits beyond that — the chip text is small and a 2-digit number
 *  reads fine where a circled glyph would be hard to distinguish. */
const CIRCLED_DIGITS = [
  "①", "②", "③", "④",
  "⑤", "⑥", "⑦", "⑧",
  "⑨", "⑩", "⑪", "⑫",
  "⑬", "⑭", "⑮", "⑯",
  "⑰", "⑱", "⑲", "⑳",
]

export interface BeatMaskStripProps {
  /** Active slice resolution.  Drives the chip count + visibility. */
  resolution: string
  /** Current mask: an array of booleans (length == chip count) or
   *  null for "all on" / "no mask" (the default). */
  mask:       boolean[] | null
  /** Called with the new mask.  All-true is normalised to null
   *  inside the component before invoking. */
  onChange:   (mask: boolean[] | null) => void
  /** Optional disabled state. */
  disabled?:  boolean
}

export function BeatMaskStrip({
  resolution,
  mask,
  onChange,
  disabled,
}: BeatMaskStripProps) {
  const count = RESOLUTION_CHIP_COUNT[resolution]

  // For resolutions outside the supported chip-count set (1/64,
  // 1/128, MAX RANDOM), the beat mask chip strip is impractical
  // — 64+ chips per bar overflow horizontally and don't read at
  // small sizes.  Instead of going completely silent, render a
  // dormant placeholder so the user can SEE the beat mask exists
  // and understand why it's not interactive at the current
  // resolution.  This is a UX improvement over v0.1.6 where the
  // strip just disappeared.
  if (!count) {
    return (
      <div
        className={cn(
          "flex flex-col gap-1",
          "rounded border border-dashed border-slurm-border-2",
          "px-3 py-2",
          "select-none",
        )}
      >
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.15em] text-slurm-muted">
          <span>beat mask</span>
          <span className="font-mono normal-case tracking-normal text-slurm-fg">
            {resolution}
          </span>
          <span className="text-slurm-muted/70">· dormant</span>
        </div>
        <div className="text-[10px] text-slurm-muted/70 leading-snug">
          {resolution === "MAX RANDOM"
            ? "MAX RANDOM has no fixed beat grid — slice durations are drawn from a trimodal distribution, so per-beat masking doesn't apply."
            : "Chip count would be too dense at this resolution. Switch to 1/32 or below to drop individual beats."}
        </div>
      </div>
    )
  }

  // Resolve the effective mask: if the stored mask doesn't match the
  // current chip count (e.g., resolution just changed), or is null,
  // treat as all-true.  Parent SHOULD also reset mask to null on
  // resolution change for correctness, but this guard keeps us safe
  // even if it doesn't.
  const effective: boolean[] =
    mask && mask.length === count ? mask : new Array(count).fill(true)

  const toggle = (i: number) => {
    if (disabled) return
    const next = [...effective]
    next[i] = !next[i]
    // Normalise all-true to null so slurmcore skips the filter step.
    onChange(next.every((v) => v) ? null : next)
  }

  return (
    <div className="flex flex-col gap-1">
      <div
        className={cn(
          "flex items-center gap-2",
          "text-[10px] uppercase tracking-[0.15em] text-slurm-muted",
          "select-none",
        )}
      >
        <span>beat mask</span>
        <span className="font-mono normal-case tracking-normal text-slurm-fg">
          {resolution}
        </span>
        <span>· click to drop a beat</span>
      </div>

      {/* MaxFire peeks up from behind the chip grid on hover.  The
          easter-egg wrapper is purely decorative — pointer-events on
          the gif are off, so chip clicks pass through normally. */}
      <EasterEggHover
        gifSrc={maxFireGif}
        width={400}
        height={278}
        anchor="peek-up-behind"
        alt="MaxFire peeking up"
      >
      <div
        role="group"
        aria-label="beat mask"
        className={cn(
          // Fixed 8-column grid — beats wrap into a new row every 8.
          //   1/1  → 1 chip   (1 row, 1 of 8 cells used)
          //   1/2  → 2 chips  (1 row)
          //   1/4  → 4 chips  (1 row)
          //   1/8  → 8 chips  (1 row)
          //   1/16 → 16 chips (2 rows of 8)
          //   1/32 → 32 chips (4 rows of 8)
          // Gives a stable rectangular layout regardless of available
          // width, so the strip can sit predictably beside knobs.
          "grid grid-cols-8 gap-1",
          // Cap the strip's max width so it doesn't stretch oddly when
          // it has fewer than 8 chips and lots of horizontal room.
          "w-fit",
          // Opaque background — the easter egg sits BEHIND this grid
          // (z-index 0 vs the grid contents at z-index 1), so the
          // chips need a non-transparent background to occlude the
          // bottom 80% of the gif and only let Max's head peek above.
          "bg-slurm-bg/80 rounded relative",
          disabled && "pointer-events-none opacity-50",
        )}
      >
        {effective.map((on, i) => (
          <Tip
            key={i}
            text={
              <>
                <strong>Beat {i + 1}</strong> of {count} ({resolution}).
                Currently <strong>{on ? "kept" : "dropped"}</strong>.
                Click to {on ? "drop this beat from every bar" : "restore this beat"}.
                The pattern repeats across the whole song — every Nth slice
                in the output is filtered through this mask.
              </>
            }
          >
            <button
              type="button"
              role="checkbox"
              aria-checked={on}
              onClick={() => toggle(i)}
              className={cn(
                "h-7 w-9 select-none rounded text-[14px] leading-none",
                "transition-colors",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                on
                  ? cn(
                      "border border-primary bg-primary/10 text-primary",
                      "hover:bg-primary/20",
                    )
                  : cn(
                      "border border-dashed border-slurm-border-2 text-slurm-muted/60",
                      "hover:border-slurm-border-2/80 hover:text-slurm-muted",
                    ),
              )}
            >
              {CIRCLED_DIGITS[i] ?? (i + 1)}
            </button>
          </Tip>
        ))}
      </div>
      </EasterEggHover>
    </div>
  )
}
