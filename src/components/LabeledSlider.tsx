// ──────────────────────────────────────────────────────────────────────
// src/components/LabeledSlider.tsx — The canonical control-row pattern
// ──────────────────────────────────────────────────────────────────────
//
// Implements docs/UI_DESIGN_BRIEF.md §5.1 form-row pattern:
//
//   [ label  ────slider────  value · unit  optional-extras ]
//
// Every numeric param in Slurmify uses this row; once you've written
// 3-4 of them in App.tsx the rest become trivial.  The component owns:
//
//   • label width (140px so multi-row stacks align)
//   • slider min/max/step (passed through)
//   • formatted value display (right-aligned, tabular-nums)
//   • optional unit text
//   • optional "extras" slot — used in Phase E3 for the ms ⇄ ♪ toggle
//
// Usage:
//   <LabeledSlider
//     label="speed"
//     min={0.05} max={4.0} step={0.05}
//     value={speed}
//     onChange={setSpeed}
//     formatValue={(v) => v.toFixed(2)}
//     unit="×"
//   />
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Slider } from "@/components/ui/slider"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface LabeledSliderProps {
  label:    string
  value:    number
  onChange: (v: number) => void

  min:  number
  max:  number
  step: number

  /** Convert the numeric value to a display string.  Defaults to
   *  `String(value)`.  Use this for fixed-decimal formatting,
   *  percentages, sign-aware semitone display, etc. */
  formatValue?: (v: number) => string

  /** Right-side unit text (e.g., "ms", "%", "×", "st").  Optional. */
  unit?: string

  /** Right-side extras slot — typically the ms ⇄ ♪ toggle (Phase E3)
   *  or a small "info" tooltip trigger.  Rendered after the unit. */
  extras?: React.ReactNode

  /** Optional info text shown under the row.  Use sparingly — the
   *  design brief favors tooltips over inline help. */
  hint?: React.ReactNode

  /** Verbose tooltip for the label.  Hover shows a Radix tooltip
   *  with this content.  Recommended for every control — pointing
   *  at the label and seeing a concise paragraph is the new
   *  on-demand help pattern (replaces v0.1.6's inline `info=`
   *  text). */
  tooltip?: React.ReactNode

  /** Disabled state — greys out the row. */
  disabled?: boolean

  /** Tailwind className for the outer wrapper (rare; usually unused). */
  className?: string
}

export function LabeledSlider({
  label,
  value,
  onChange,
  min,
  max,
  step,
  formatValue,
  unit,
  extras,
  hint,
  tooltip,
  disabled,
  className,
}: LabeledSliderProps) {
  const display = formatValue ? formatValue(value) : String(value)

  return (
    <div
      className={cn(
        "flex flex-col gap-0.5 py-1",
        disabled && "opacity-50",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        {/* Label — fixed width so multiple rows align.  140px holds
            even our longer labels ("transient sensitivity").
            Wrapped in <Tip> ONLY when a tooltip is actually provided
            — keeps Radix out of the render path on rows that don't
            need help, which avoids any asChild/forwardRef edge cases
            on plain <label> elements. */}
        {tooltip ? (
          <Tip text={tooltip}>
            <label
              className={cn(
                "w-32 shrink-0 text-[12px] text-slurm-muted",
                "select-none",
                "cursor-help underline decoration-dotted decoration-slurm-border-2 underline-offset-4",
              )}
            >
              {label}
            </label>
          </Tip>
        ) : (
          <label
            className={cn(
              "w-32 shrink-0 text-[12px] text-slurm-muted",
              "select-none",
            )}
          >
            {label}
          </label>
        )}

        {/* Slider — eats the rest of the row. */}
        <Slider
          className="flex-1"
          value={[value]}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onValueChange={([v]) => onChange(v)}
        />

        {/* Value display — fixed width (so digits don't shift the
            slider when value crosses 9 ↔ 10), tabular numerals (so
            decimals align), right-aligned. */}
        <span
          className={cn(
            "w-16 shrink-0 text-right text-[12px] text-slurm-fg",
            "font-mono tabular-nums",
          )}
        >
          {display}
          {unit && <span className="ml-1 text-slurm-muted">{unit}</span>}
        </span>

        {/* Extras slot — typically a small toggle or icon button.
            We give it a sensible padded area (no collapse on empty). */}
        {extras && <span className="flex shrink-0 items-center">{extras}</span>}
      </div>

      {/* Hint — secondary explanation under the row.  Optional,
          rendered indented to align under the slider. */}
      {hint && (
        <div className="ml-32 pl-3 text-[10px] text-slurm-muted">{hint}</div>
      )}
    </div>
  )
}
