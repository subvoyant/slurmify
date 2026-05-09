// ──────────────────────────────────────────────────────────────────────
// src/components/KnobToggle.tsx — Vertical-layout switch in a knob cell
// ──────────────────────────────────────────────────────────────────────
//
// The boolean equivalent of LabeledKnob.  Same vertical cell structure
// (control on top, label below, value at the bottom) and same fixed
// 76px width so booleans tile cleanly inside knob rows alongside their
// related rotaries:
//
//   [transient]  [envelope]  [shuffle]
//   [   ⊙   ]    [   ⊙   ]    [ ⚪——⚫ ]
//    transient    envelope     shuffle
//      0.50         2.0 ms       ON
//
// LabeledSwitch (horizontal layout) is still the right choice for
// settings panels and standalone-row toggles; KnobToggle is for when
// the toggle conceptually belongs in the same row as nearby knobs.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Switch } from "@/components/ui/switch"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface KnobToggleProps {
  label:           string
  checked:         boolean
  onCheckedChange: (v: boolean) => void
  /** Verbose tooltip; same content rules as LabeledSlider's tooltip. */
  tooltip?:        React.ReactNode
  disabled?:       boolean
  className?:      string
}

export function KnobToggle({
  label,
  checked,
  onCheckedChange,
  tooltip,
  disabled,
  className,
}: KnobToggleProps) {
  const cell = (
    <div
      className={cn(
        "flex flex-col items-center gap-1",
        "w-[76px] shrink-0 select-none",
        disabled && "opacity-50",
        className,
      )}
    >
      {/* 56px-tall control area matches the Knob diameter exactly so
          a row mixing knobs and toggles aligns vertically.  The Switch
          itself is small (h-4 w-7) — we center it in this taller box. */}
      <div className="flex h-14 items-center justify-center">
        <Switch
          checked={checked}
          onCheckedChange={onCheckedChange}
          disabled={disabled}
        />
      </div>

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
          "text-[11px] font-mono uppercase tabular-nums leading-tight",
          checked ? "text-primary" : "text-slurm-muted",
        )}
      >
        {checked ? "on" : "off"}
      </div>
    </div>
  )

  return tooltip ? <Tip text={tooltip}>{cell}</Tip> : cell
}
