// ──────────────────────────────────────────────────────────────────────
// src/components/ui/slider.tsx — Radix Slider, themed
// ──────────────────────────────────────────────────────────────────────
//
// Standard shadcn Slider primitive on top of Radix's accessible
// SliderPrimitive.  Hooked into our --primary HSL token so all three
// skins re-tint the track + range + thumb automatically.
//
// Usage:
//   <Slider value={[42]} min={0} max={100} step={1}
//           onValueChange={([v]) => setX(v)} />
//
// Radix's value is always an array (to support range sliders with two
// thumbs); we always use single-thumb so callers destructure [v].
//
// Accessibility comes for free: keyboard (←/→/Home/End), screen
// reader announcements, focus ring, ARIA roles.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"
import { cn } from "@/lib/utils"

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex w-full touch-none select-none items-center",
      className,
    )}
    {...props}
  >
    {/* Track — the background line.  Use slurm-border-2 (slightly
        lighter than the panel surface) so it reads against the rack
        body without competing with the active range. */}
    <SliderPrimitive.Track
      className={cn(
        "relative h-1.5 w-full grow overflow-hidden rounded-full",
        "bg-slurm-border-2/60",
      )}
    >
      {/* Range — the filled portion left of the thumb.  Uses --primary
          (cyan/mint/LED-green per skin) so the slider feels alive. */}
      <SliderPrimitive.Range className="absolute h-full bg-primary" />
    </SliderPrimitive.Track>
    {/* Thumb — small circle.  Tighter than shadcn default (h-3.5 vs
        h-4) to match the design brief's compact density. */}
    <SliderPrimitive.Thumb
      className={cn(
        "block h-3.5 w-3.5 rounded-full border border-primary bg-slurm-bg shadow",
        "transition-colors hover:bg-slurm-surface",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-slurm-bg",
        "disabled:pointer-events-none disabled:opacity-50",
      )}
    />
  </SliderPrimitive.Root>
))
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
