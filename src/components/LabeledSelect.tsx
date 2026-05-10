// ──────────────────────────────────────────────────────────────────────
// src/components/LabeledSelect.tsx — Dropdown control row
// ──────────────────────────────────────────────────────────────────────
//
// Mirror of LabeledSlider/LabeledSwitch for enum params (output_format,
// future preset selector, etc.).  Wraps shadcn's Select primitive in
// the design-brief row pattern.
//
// Usage:
//   <LabeledSelect
//     label="format"
//     value={fmt}
//     onValueChange={setFmt}
//     options={[
//       { value: "wav", label: "WAV" },
//       { value: "mp3", label: "MP3" },
//     ]}
//     hint="lossless except mp3/aac"
//   />
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface LabeledSelectOption<V extends string = string> {
  value: V
  label: string
}

export interface LabeledSelectProps<V extends string = string> {
  label:         string
  value:         V
  onValueChange: (v: V) => void
  options:       LabeledSelectOption<V>[]
  /** Optional placeholder when value is empty (rare in our case
   *  since every param has a default). */
  placeholder?:  string
  hint?:         React.ReactNode
  /** Verbose tooltip on hover; see LabeledSlider for usage notes. */
  tooltip?:      React.ReactNode
  disabled?:     boolean
  className?:    string
  /** Width of the dropdown trigger.  Defaults to 7rem; the format
   *  dropdown only shows 4-letter codes, which fit in 7rem.  Future
   *  enum dropdowns with longer labels can override. */
  triggerWidth?: string

  /** When true, the label is content-sized (instead of the default
   *  fixed `w-32` 128 px) and sits with a tight `gap-2` against the
   *  trigger.  Use for inline / horizontal layouts where the
   *  default fixed-width label leaves an awkward gap that makes
   *  the label and input look disconnected.  Default `false`
   *  preserves the legacy stacked-row behavior. */
  compactLabel?: boolean
}

export function LabeledSelect<V extends string = string>({
  label,
  value,
  onValueChange,
  options,
  placeholder,
  hint,
  tooltip,
  disabled,
  className,
  triggerWidth = "7rem",
  compactLabel = false,
}: LabeledSelectProps<V>) {
  // Label size + row gap collapse together in compact mode so the
  // label visually anchors to the input instead of floating in 128 px
  // of empty space.
  const labelClasses = compactLabel
    ? "shrink-0 text-[12px] text-slurm-muted select-none"
    : "w-32 shrink-0 text-[12px] text-slurm-muted select-none"
  const rowGap = compactLabel ? "gap-2" : "gap-3"
  return (
    <div
      className={cn(
        "flex flex-col gap-0.5 py-1",
        disabled && "opacity-50",
        className,
      )}
    >
      <div className={cn("flex items-center", rowGap)}>
        {tooltip ? (
          <Tip text={tooltip}>
            <label
              className={cn(
                labelClasses,
                "cursor-help underline decoration-dotted decoration-slurm-border-2 underline-offset-4",
              )}
            >
              {label}
            </label>
          </Tip>
        ) : (
          <label className={labelClasses}>
            {label}
          </label>
        )}
        <Select
          value={value}
          onValueChange={(v) => onValueChange(v as V)}
          disabled={disabled}
        >
          <SelectTrigger
            className="shrink-0"
            style={{ width: triggerWidth }}
          >
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent>
            {options.map(({ value: v, label: l }) => (
              <SelectItem key={v} value={v}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {hint && (
        <div className={cn(
          "text-[10px] text-slurm-muted",
          // In compact mode the label is content-sized, so the
          // ml-32 indent for the hint no longer applies — drop the
          // indent so the hint sits directly under the row.
          compactLabel ? "" : "ml-32 pl-3",
        )}>{hint}</div>
      )}
    </div>
  )
}
