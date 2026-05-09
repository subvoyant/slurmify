// ──────────────────────────────────────────────────────────────────────
// src/components/LabeledSwitch.tsx — Boolean control row, brief-conformant
// ──────────────────────────────────────────────────────────────────────
//
// Mirror of LabeledSlider for boolean params (preserve_pitch,
// randomize_order, etc.).  Same label width as LabeledSlider so
// alternating slider + switch rows visually align.
//
// Usage:
//   <LabeledSwitch
//     label="preserve pitch"
//     checked={preservePitch}
//     onCheckedChange={setPreservePitch}
//     hint="off = chipmunk effect (pitch rises with speed)"
//   />
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Switch } from "@/components/ui/switch"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface LabeledSwitchProps {
  label:           string
  checked:         boolean
  onCheckedChange: (v: boolean) => void
  /** Optional secondary line under the row.  In contrast to slider
   *  hints (which are usually about value semantics), switch hints
   *  are usually about the OFF state ("off = chipmunk effect"). */
  hint?:           React.ReactNode
  /** Verbose tooltip on hover; see LabeledSlider for usage notes. */
  tooltip?:        React.ReactNode
  disabled?:       boolean
  className?:      string
}

export function LabeledSwitch({
  label,
  checked,
  onCheckedChange,
  hint,
  tooltip,
  disabled,
  className,
}: LabeledSwitchProps) {
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
                "select-none cursor-pointer",
                "underline decoration-dotted decoration-slurm-border-2 underline-offset-4",
              )}
              onClick={() => !disabled && onCheckedChange(!checked)}
            >
              {label}
            </label>
          </Tip>
        ) : (
          <label
            className={cn(
              "w-32 shrink-0 text-[12px] text-slurm-muted",
              "select-none cursor-pointer",
            )}
            onClick={() => !disabled && onCheckedChange(!checked)}
          >
            {label}
          </label>
        )}
        <Switch
          checked={checked}
          onCheckedChange={onCheckedChange}
          disabled={disabled}
        />
        {/* Right-side state label so the on/off is readable at a
            glance even if the small Switch thumb is ambiguous. */}
        <span
          className={cn(
            "text-[11px] font-mono uppercase tracking-wider",
            checked ? "text-primary" : "text-slurm-muted",
          )}
        >
          {checked ? "on" : "off"}
        </span>
      </div>
      {hint && (
        <div className="ml-32 pl-3 text-[10px] text-slurm-muted">{hint}</div>
      )}
    </div>
  )
}
