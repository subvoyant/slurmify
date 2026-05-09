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
}: LabeledSelectProps<V>) {
  return (
    <div
      className={cn(
        "flex flex-col gap-0.5 py-1",
        disabled && "opacity-50",
        className,
      )}
    >
      <div className="flex items-center gap-3">
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
        <div className="ml-32 pl-3 text-[10px] text-slurm-muted">{hint}</div>
      )}
    </div>
  )
}
