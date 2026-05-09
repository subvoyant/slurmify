// ──────────────────────────────────────────────────────────────────────
// src/components/LabeledTextbox.tsx — Text/number input row
// ──────────────────────────────────────────────────────────────────────
//
// The text-input equivalent of LabeledSlider/Switch/Select — design
// brief §5.1 form-row pattern.  Used for BPM override, seed, and
// any other free-form value entry.
//
// String-typed by default.  Use `type="number"` for numeric inputs
// — the underlying Input primitive (src/components/ui/input.tsx)
// suppresses the ugly browser spinner UI and applies tabular nums.
//
// Note on numeric handling: HTML number inputs send strings to JS,
// but valueAsNumber returns a parsed Number.  The caller decides how
// to handle "user is mid-typing" partial values.  See BPM override
// in App.tsx for the canonical pattern.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Input } from "@/components/ui/input"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface LabeledTextboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> {
  label: string
  value: string
  onChange: (v: string) => void

  /** Optional unit suffix (e.g., "BPM", "Hz", "ms").  Rendered in
   *  the muted color alongside the input. */
  unit?: string

  /** Right-side extras slot — e.g., a small button next to the input
   *  for scripted helpers like "auto-detect". */
  extras?: React.ReactNode

  /** Optional secondary line under the row (sparingly — tooltips
   *  preferred). */
  hint?: React.ReactNode

  /** Verbose tooltip on the label.  Recommended. */
  tooltip?: React.ReactNode

  /** Width of the input field itself.  Defaults to "8rem" — fits
   *  3-4 digits comfortably. */
  inputWidth?: string

  /** Wrapper className. */
  wrapperClassName?: string
}

export function LabeledTextbox({
  label,
  value,
  onChange,
  unit,
  extras,
  hint,
  tooltip,
  inputWidth = "8rem",
  wrapperClassName,
  disabled,
  className,
  ...inputProps
}: LabeledTextboxProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-0.5 py-1",
        disabled && "opacity-50",
        wrapperClassName,
      )}
    >
      <div className="flex items-center gap-3">
        {/* Label — fixed 128px width to align with LabeledSlider /
            Switch / Select rows when stacked together. */}
        {tooltip ? (
          <Tip text={tooltip}>
            <label
              className={cn(
                "w-32 shrink-0 text-[12px] text-slurm-muted",
                "select-none cursor-help underline decoration-dotted decoration-slurm-border-2 underline-offset-4",
              )}
            >
              {label}
            </label>
          </Tip>
        ) : (
          <label className="w-32 shrink-0 text-[12px] text-slurm-muted select-none">
            {label}
          </label>
        )}

        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className={cn(className)}
          style={{ width: inputWidth }}
          {...inputProps}
        />

        {unit && (
          <span className="text-[11px] text-slurm-muted font-mono shrink-0">
            {unit}
          </span>
        )}

        {extras && (
          <span className="flex shrink-0 items-center gap-1">{extras}</span>
        )}
      </div>

      {hint && (
        <div className="ml-32 pl-3 text-[10px] text-slurm-muted">{hint}</div>
      )}
    </div>
  )
}
