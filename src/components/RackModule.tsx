// ──────────────────────────────────────────────────────────────────────
// src/components/RackModule.tsx — Reason-style rack module frame
// ──────────────────────────────────────────────────────────────────────
//
// The primary visual structure for Slurmify v0.2.0.  Every major control
// group (INPUT, SLICING, STRETCH, STUTTER, FX, OUTPUT, etc.) is a
// RackModule with its own identity color.  See docs/UI_DESIGN_BRIEF.md
// §9 for the full spec; this is the implementation.
//
// Anatomy:
//   ┌─────────────────────────────────────────────────────────────┐
//   │ ●  M O D U L E   N A M E                       SLURM ─ ┤  ← header
//   ├─────────────────────────────────────────────────────────────┤
//   │  body (children render here)                                │
//   └─────────────────────────────────────────────────────────────┘
//
// Header is a fixed 28px-tall bar in the module's identity color.
// The status dot on the left can be `idle`, `active` (pulsing), or
// `error` (red).  The right side carries the SLURM brand strip + an
// optional badge slot for module-specific status (e.g., "1/3" step
// number, "READY", file count, etc.).
//
// Body is full-width, padded, and renders whatever children we pass.
// Background color is --slurm-surface so the body re-tints with skin.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"
import { RACK_COLORS, type RackColorKey } from "@/lib/rack-colors"

export interface RackModuleProps {
  /** Module identity (drives header color + brand strip). */
  color: RackColorKey
  /** Module name shown in the header.  Will be tracked-out + uppercase
   *  by the component; pass the natural-case name (e.g., "input"). */
  name: string
  /** Optional right-side badge in the header (status text, step #, etc.). */
  badge?: React.ReactNode
  /** Status dot kind: "idle" (matte), "active" (pulsing), "error" (red). */
  status?: "idle" | "active" | "error"
  /** Body content. */
  children: React.ReactNode
  /** Additional className applied to the outer module wrapper. */
  className?: string
  /** Additional className applied to the body container only. */
  bodyClassName?: string
}

export function RackModule({
  color,
  name,
  badge,
  status = "idle",
  children,
  className,
  bodyClassName,
}: RackModuleProps) {
  const c = RACK_COLORS[color]

  // Status dot color resolves from the rack color (idle/active) or
  // the danger token (error).  Active state pulses via the
  // animate-pulse-glow keyframes from tailwind.config.
  const dotColor =
    status === "error" ? "var(--slurm-danger)" : c.dot
  const pulsing = status === "active"

  return (
    <section
      className={cn(
        "overflow-hidden rounded-md border border-slurm-border-2",
        "shadow-[0_1px_0_rgba(255,255,255,0.04)_inset,0_1px_3px_rgba(0,0,0,0.6)]",
        className,
      )}
    >
      {/* ── Header bar ──────────────────────────────────────────── */}
      <header
        className={cn(
          "flex h-7 items-center gap-2 px-2",
          "select-none",
          // Subtle inner shadow so the header has depth (no
          // photorealism, just hint of inset top edge).
          "shadow-[inset_0_-1px_0_rgba(0,0,0,0.35)]",
        )}
        style={{
          backgroundColor: c.header,
          // Subtle vertical gradient — top a touch lighter, bottom a
          // touch darker — to evoke a real metal panel without going
          // full skeuomorphic.
          backgroundImage:
            "linear-gradient(180deg, rgba(255,255,255,0.06), rgba(0,0,0,0.18))",
        }}
      >
        {/* Status dot */}
        <span
          className={cn(
            "inline-block h-2 w-2 shrink-0 rounded-full",
            pulsing && "animate-pulse-glow",
          )}
          style={{
            backgroundColor: dotColor,
            boxShadow: pulsing
              ? `0 0 6px ${dotColor}`
              : `0 0 3px rgba(0,0,0,0.5) inset, 0 0 4px ${dotColor}`,
          }}
        />

        {/* Module name (tracked-out, uppercase) */}
        <span
          className={cn(
            "text-[11px] font-semibold uppercase tracking-[0.2em]",
            "text-white/90",
            "drop-shadow-[0_1px_0_rgba(0,0,0,0.6)]",
          )}
        >
          {name}
        </span>

        {/* Optional badge (right-side label slot, BEFORE the brand strip) */}
        {badge && (
          <span className="ml-auto text-[10px] font-medium uppercase tracking-[0.15em] text-white/60">
            {badge}
          </span>
        )}

        {/* Brand strip — small wordmark on the right edge of every header.
            Uses the same color as the header but slightly darker so it
            reads as part of the panel, not floating type. */}
        <span
          className={cn(
            "ml-auto flex items-center gap-1 pl-2",
            "text-[9px] font-bold uppercase tracking-[0.25em] text-white/45",
          )}
          style={badge ? { marginLeft: "8px" } : undefined}
        >
          <span
            className="inline-block h-3 w-[2px] rounded-sm"
            style={{ backgroundColor: c.on }}
          />
          slurm
        </span>
      </header>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div
        className={cn(
          "bg-slurm-surface p-3",
          // Subtle highlight at top of body to indicate the header sits on top.
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]",
          bodyClassName,
        )}
      >
        {children}
      </div>
    </section>
  )
}
