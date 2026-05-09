// ──────────────────────────────────────────────────────────────────────
// src/components/ui/input.tsx — Themed text/number input primitive
// ──────────────────────────────────────────────────────────────────────
//
// The standard shadcn Input theming, sized down to match our compact
// design brief (h-7 ~ 28px tall, 12px text — about 80% the size of
// shadcn defaults).  Used for BPM override, seed, in/out trim, and
// any future text/number entry.
//
// Forward refs so React Hook Form (or any other consumer that needs
// imperative focus) keeps working.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  function Input({ className, type = "text", ...props }, ref) {
    return (
      <input
        ref={ref}
        type={type}
        className={cn(
          // Sizing — tight, 28px tall to match small button + select
          // heights elsewhere in the rack.
          "h-7 w-full rounded border bg-slurm-surface px-2 py-1",
          "text-[12px] text-slurm-fg",
          "placeholder:text-slurm-muted",

          // Border + focus — primary token at focus so all skins
          // re-tint cleanly.
          "border-slurm-border",
          "focus:outline-none focus:ring-1 focus:ring-slurm-cyan focus:border-slurm-cyan",

          // Disabled state
          "disabled:cursor-not-allowed disabled:opacity-50",

          // Number inputs: kill the spinner buttons (ugly + small;
          // we're going for a "panel readout" aesthetic, and the user
          // can use scroll wheel or arrow keys for nudging).
          "[&::-webkit-inner-spin-button]:appearance-none",
          "[&::-webkit-outer-spin-button]:appearance-none",
          "[&[type='number']]:[appearance:textfield]",

          // Tabular nums for numeric values so digits don't jiggle
          // as the user types.
          type === "number" && "font-mono tabular-nums",

          className,
        )}
        {...props}
      />
    )
  },
)
