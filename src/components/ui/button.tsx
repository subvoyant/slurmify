// ──────────────────────────────────────────────────────────────────────
// src/components/ui/button.tsx — shadcn-style Button primitive
// ──────────────────────────────────────────────────────────────────────
//
// Standard shadcn Button — variant + size props via class-variance-
// authority (cva).  Hooks into our HSL semantic tokens (--primary,
// --secondary, --destructive, etc.) so all three skins re-tint the
// button automatically.
//
// Reference for future shadcn primitives copied into src/components/ui/
// (Slider, Card, Tabs, Toggle, Progress, Dialog, etc.):
//   • Path:    src/components/ui/<name>.tsx
//   • Imports: cn from @/lib/utils, cva from class-variance-authority
//   • Forward refs via React.forwardRef so the primitive can be used
//     with libraries that pass refs (Radix UI, react-hook-form, etc.).
//
// Usage:
//   <Button>Slurmify</Button>
//   <Button variant="secondary">Cancel</Button>
//   <Button variant="destructive" size="sm">Delete</Button>
//   <Button variant="ghost" size="icon"><X /></Button>
//
// All variants are picked up automatically by the active skin:
//   default        → uses --primary (cyan/mint/LED-green)
//   destructive    → uses --destructive (red across all skins)
//   outline        → transparent w/ border
//   secondary      → uses --secondary (a muted surface tint)
//   ghost          → transparent until hover
//   link           → underlined text, no chrome
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

// cva builds a className composer.  The first arg is the BASE class
// string; the variants object lists each axis (variant, size).
// `defaultVariants` set what wins when callers don't pass props.
const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md text-sm font-medium",
    "transition-colors focus-visible:outline-none",
    "focus-visible:ring-1 focus-visible:ring-ring",
    "disabled:pointer-events-none disabled:opacity-50",
    // Lucide icons inside buttons get sized to fit the line.
    "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  ),
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          cn(
            "border border-input bg-transparent shadow-sm",
            "hover:bg-accent hover:text-accent-foreground",
          ),
        secondary:
          // shadcn's default `hover:bg-secondary/80` uses an opacity
          // reduction to signal hover.  That math goes the wrong
          // direction in our dark-on-dark theme — secondary is too
          // close to the background for opacity to register.  We
          // swap in a brightness filter that lifts ALL channels
          // 35% on hover; works across all three skins identically.
          cn(
            "bg-secondary text-secondary-foreground shadow-sm",
            "transition-[filter,background-color] duration-150",
            "hover:brightness-[1.35]",
          ),
        ghost:
          "hover:bg-accent hover:text-accent-foreground",
        link:
          "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm:      "h-8 rounded-md px-3 text-xs",
        lg:      "h-10 rounded-md px-8",
        icon:    "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size:    "default",
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** When true, render as the child element instead of a <button>.
   *  Useful for letting the Button styles wrap an <a> tag.  We don't
   *  use this in v0.2.0 yet — it requires Radix Slot which isn't
   *  installed.  Stub the prop here so we don't have to widen the
   *  interface later.  Pass-through implemented when needed. */
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild: _asChild, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    )
  },
)
Button.displayName = "Button"

// Re-exported so consumers can pluck just the variant function for
// composing other components (e.g., styling an <a> like a button via
// a className prop).
export { buttonVariants }
