// ──────────────────────────────────────────────────────────────────────
// src/components/LabeledKnob.tsx — Vertical knob + label + value cell
// ──────────────────────────────────────────────────────────────────────
//
// The knob equivalent of LabeledSlider.  Vertical layout suited for
// tiling horizontally inside a rack module body:
//
//   ┌────────────────────────┐
//   │    ╭──────╮            │
//   │   (   ●   )   ← knob   │
//   │    ╰──────╯            │
//   │     speed              │ ← label (small caps, muted)
//   │     2.00 ×             │ ← value (mono, primary on hover)
//   └────────────────────────┘
//
// Width is fixed (~80px) so multiple LabeledKnobs in a flex row tile
// uniformly.  The whole cell is wrapped in a Tip when a tooltip is
// provided — hovering anywhere in the cell triggers the verbose help.
//
// API mirrors LabeledSlider's so swapping a row of sliders for a row
// of knobs is just changing the import + element name.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Knob } from "@/components/ui/knob"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface LabeledKnobProps {
  label:    string
  value:    number
  onChange: (v: number) => void

  min:  number
  max:  number
  step: number

  /** Convert numeric value → display string (e.g. "2.00", "+5"). */
  formatValue?: (v: number) => string

  /** Right-side unit suffix (e.g. "ms", "%", "×", "st"). */
  unit?: string

  /** Default value for double-click reset.  Falls back to (min+max)/2. */
  defaultValue?: number

  /** Knob diameter in pixels.  Default 56. */
  size?: number

  /** Verbose tooltip — same content rules as LabeledSlider's tooltip
   *  prop.  Recommended for every knob. */
  tooltip?: React.ReactNode

  /** Disabled state — greys out + ignores input. */
  disabled?: boolean

  className?: string
}

export function LabeledKnob({
  label,
  value,
  onChange,
  min,
  max,
  step,
  formatValue,
  unit,
  defaultValue,
  size = 56,
  tooltip,
  disabled,
  className,
}: LabeledKnobProps) {
  const display = formatValue ? formatValue(value) : String(value)
  const ariaText = unit ? `${display} ${unit}` : display

  // The cell is the same fixed width regardless of value text length so
  // a row of knobs tiles uniformly.  76px holds 4-character values
  // ("100%", "1.00", "+24") and the knob itself; bump to 84-96 for
  // wider value strings.
  const cell = (
    <div
      className={cn(
        "flex flex-col items-center gap-1",
        "w-[76px] shrink-0 select-none",
        disabled && "opacity-50",
        className,
      )}
    >
      <Knob
        value={value}
        onChange={onChange}
        min={min}
        max={max}
        step={step}
        size={size}
        defaultValue={defaultValue}
        disabled={disabled}
        ariaLabel={label}
        ariaValueText={ariaText}
      />
      <div
        className={cn(
          "text-[10px] uppercase tracking-[0.05em] text-slurm-muted",
          "leading-tight text-center",
        )}
      >
        {label}
      </div>
      <div
        className={cn(
          "text-[11px] font-mono tabular-nums leading-tight",
          "text-slurm-fg",
        )}
      >
        {display}
        {unit && <span className="ml-0.5 text-slurm-muted">{unit}</span>}
      </div>
    </div>
  )

  // Wrap the entire cell in a tooltip — hovering the knob OR the
  // label OR the value all trigger the help, which feels more
  // natural than only-on-label.
  return tooltip ? <Tip text={tooltip}>{cell}</Tip> : cell
}
