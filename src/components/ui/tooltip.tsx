// ──────────────────────────────────────────────────────────────────────
// src/components/ui/tooltip.tsx — Radix Tooltip, themed
// ──────────────────────────────────────────────────────────────────────
//
// Verbose, hover-on-demand explanations for every control + indicator.
// Built on Radix's Tooltip primitive (full a11y: focusable, keyboard-
// dismissable, screen-reader-announced).
//
// Two ways to use:
//
// 1. Composable parts (full control):
//   <TooltipProvider>
//     <Tooltip>
//       <TooltipTrigger asChild><button>foo</button></TooltipTrigger>
//       <TooltipContent>Helpful description.</TooltipContent>
//     </Tooltip>
//   </TooltipProvider>
//
// 2. Convenience wrapper (most common):
//   <Tip text="Helpful description.">
//     <button>foo</button>
//   </Tip>
//
// The provider is mounted ONCE at the root (App.tsx) so individual
// Tip uses don't have to mount their own.  delayDuration = 300ms
// matches macOS native tooltip timing.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "@/lib/utils"

// ── Building blocks ───────────────────────────────────────────────────

const TooltipProvider = TooltipPrimitive.Provider
const Tooltip         = TooltipPrimitive.Root
const TooltipTrigger  = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 max-w-[260px] overflow-hidden rounded",
        "border border-slurm-border bg-slurm-surface px-2 py-1.5",
        "text-[11px] leading-snug text-slurm-fg",
        "shadow-md",
        "animate-in fade-in-0 zoom-in-95",
        "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
        "data-[side=bottom]:slide-in-from-top-1 data-[side=left]:slide-in-from-right-1",
        "data-[side=right]:slide-in-from-left-1 data-[side=top]:slide-in-from-bottom-1",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

// ── Convenience wrapper ───────────────────────────────────────────────
// Use this for the 95% case where you just want a tooltip with text.

export interface TipProps {
  /** Tooltip body content.  String for simple cases; React node for
   *  multi-line / formatted content. */
  text:     React.ReactNode
  children: React.ReactNode
  /** Side the tooltip prefers (Radix flips automatically if no room). */
  side?:    "top" | "right" | "bottom" | "left"
  /** Delay before the tooltip shows (ms).  300 matches macOS native. */
  delayMs?: number
  /** When true, the tooltip is suppressed (e.g. for empty descriptions). */
  disabled?: boolean
}

/**
 * Single-element tooltip wrapper.  Children must be a single element
 * that can accept a ref (Radix's `asChild`); for non-element children
 * wrap in a `<span>` first.
 */
export function Tip({
  text,
  children,
  side = "top",
  delayMs = 300,
  disabled,
}: TipProps) {
  if (disabled || !text) {
    // Render children unwrapped so disabled tooltips don't add
    // accessibility-tree noise.
    return <>{children}</>
  }
  return (
    <Tooltip delayDuration={delayMs}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{text}</TooltipContent>
    </Tooltip>
  )
}

export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
}
