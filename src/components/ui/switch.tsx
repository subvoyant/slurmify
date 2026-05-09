// ──────────────────────────────────────────────────────────────────────
// src/components/ui/switch.tsx — Radix Switch (boolean toggle), themed
// ──────────────────────────────────────────────────────────────────────
//
// Standard shadcn Switch on top of Radix's accessible primitive.
// Used for the boolean params (preserve_pitch, randomize_order).
//
// Usage:
//   <Switch checked={preservePitch} onCheckedChange={setPreservePitch} />
//
// Tighter than shadcn default (h-4 / w-7 vs h-6 / w-11) to match
// the design brief's density.  The active "on" state uses --primary
// so all skins re-tint the lit track.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import * as SwitchPrimitive from "@radix-ui/react-switch"
import { cn } from "@/lib/utils"

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-4 w-7 shrink-0 cursor-pointer items-center rounded-full",
      "border border-transparent transition-colors",
      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-slurm-bg",
      "disabled:cursor-not-allowed disabled:opacity-50",
      "data-[state=checked]:bg-primary data-[state=unchecked]:bg-slurm-border-2",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        "pointer-events-none block h-3 w-3 rounded-full bg-slurm-bg shadow-md",
        "ring-0 transition-transform",
        "data-[state=checked]:translate-x-3 data-[state=unchecked]:translate-x-0.5",
      )}
    />
  </SwitchPrimitive.Root>
))
Switch.displayName = SwitchPrimitive.Root.displayName

export { Switch }
