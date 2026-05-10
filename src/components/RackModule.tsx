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
      // data-rack-name lets easter eggs (e.g. Bob, MaxFire) target
      // a specific rack module via CSS selector and align their
      // baseline to its top edge — see EasterEggHover's
      // `alignToSelector` prop.  Cheap, no React tree coupling.
      data-rack-name={name}
      className={cn(
        // Outer frame — slightly thicker shadow stack than before to
        // suggest the rack is lifted above the page rather than
        // flush to it.
        "relative overflow-hidden rounded-md border border-slurm-border-2",
        // flex flex-col + flex-1 on the body div: when the rack sits
        // in a CSS-grid row that stretches all cells to the tallest
        // module's height (default `align-items: stretch`), the body
        // div grows with the section so the brushed-metal background
        // fills the entire rack — no "missing background" gap below
        // the controls when one sibling rack happens to be taller.
        "flex flex-col",
        "shadow-[0_1px_0_rgba(255,255,255,0.05)_inset,0_2px_6px_rgba(0,0,0,0.65),0_8px_18px_-12px_rgba(0,0,0,0.55)]",
        className,
      )}
    >
      {/* ── Header bar ──────────────────────────────────────────── */}
      <header
        className={cn(
          "grain",                 // coarse noise overlay (CSS utility)
          "flex h-8 items-center gap-2 px-2",
          "select-none",
          // Two-stop bevel: highlight on top edge, shadow on bottom.
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.10),inset_0_-1px_0_rgba(0,0,0,0.45)]",
          // Outer hairline separator between header and body, in the
          // module's own color so the seam reads as INTENTIONAL.
          "border-b border-black/40",
        )}
        style={{
          backgroundColor: c.header,
          // Vertical gradient — light at top, dark at bottom.  Heavier
          // contrast than v0 so the panel "catches the light" more
          // visibly under the rack-shelf shadow.
          backgroundImage:
            "linear-gradient(180deg, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0.04) 30%, rgba(0,0,0,0.30) 100%)",
        }}
      >
        {/* Status LED — same as before but with a stronger inset
            shadow so the dot reads as a recessed indicator hole, with
            the LED behind shining through.  When pulsing, the halo
            doubles in size for emphasis. */}
        <span
          className={cn(
            "inline-block h-2.5 w-2.5 shrink-0 rounded-full",
            pulsing && "animate-pulse-glow",
          )}
          style={{
            backgroundColor: dotColor,
            boxShadow: pulsing
              ? `0 0 8px ${dotColor}, inset 0 0 2px rgba(0,0,0,0.6)`
              : `inset 0 0 2px rgba(0,0,0,0.6), 0 0 5px ${dotColor}`,
          }}
        />

        {/* Module name — silk-screened panel label.  Major Mono Display
            tracked out wide; a faint inset+drop combo simulates the
            ink sitting on top of the metal.  Light text on the
            module's color so each rack reads cleanly. */}
        <span
          className={cn(
            "panel-label",
            "text-[12px] text-white/95",
          )}
          style={{
            // Override the default panel-label drop shadow with a
            // colored variant so the cast shadow tints with the
            // module's identity (warmer red on red panels, etc.).
            textShadow:
              "0 1px 0 rgba(0,0,0,0.55), 0 -1px 0 rgba(255,255,255,0.08)",
          }}
        >
          {name}
        </span>

        {/* Optional badge (right-side label slot, BEFORE the brand strip).
            Uses VT323 LCD treatment when the badge is a status string
            so it reads as a tiny indicator readout. */}
        {badge && (
          <span
            className={cn(
              "ml-auto lcd",
              "text-[12px] text-white/80",
            )}
            // VT323 doesn't need the LCD glow CSS var to be a specific
            // color here — let it inherit the variable from the
            // current skin (default = orange, acid = mint, hardware =
            // amber).  Looks deliberate per-skin.
          >
            {badge}
          </span>
        )}

        {/* Brand strip — pegboard-strip wordmark on the right edge.
            Uses Major Mono Display so it matches the module name's
            etched feel. */}
        <span
          className={cn(
            "ml-auto flex items-center gap-1.5 pl-2",
            "panel-label",
            "text-[9px] text-white/55",
          )}
          style={badge ? { marginLeft: "10px" } : undefined}
        >
          <span
            className="inline-block h-3.5 w-[2px] rounded-sm"
            style={{
              backgroundColor: c.on,
              // Tiny glow so the brand strip pip reads as illuminated.
              boxShadow: `0 0 4px ${c.on}`,
            }}
          />
          slurm
        </span>
      </header>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div
        className={cn(
          "brushed",            // satin-finish noise overlay
          "relative",
          "bg-slurm-surface px-3 py-3",
          // flex-1 — claims any vertical slack the section was
          // stretched to in a grid row.  Without this, when SLICING
          // (or any taller sibling) makes the row tall, this rack's
          // body stays content-sized and a strip of unstyled
          // background shows through below the controls.
          "flex-1",
          // Highlight strip just under the header so the seam
          // between header and body reads as a real edge.  Subtle
          // bottom inset shadow simulates the body being recessed
          // into the rack frame.
          "shadow-[inset_0_1px_0_rgba(255,255,255,0.05),inset_0_-1px_0_rgba(0,0,0,0.40)]",
          bodyClassName,
        )}
      >
        {/* Four corner Phillips screws.  Each is a 10×10 absolutely-
            positioned circle with a faux-screw radial gradient.  The
            CSS variable `--screw-rot` slightly varies the slot
            rotation per screw so the row doesn't look stamped — small
            but adds a lot of "real hardware" feel.  z-index 2 keeps
            them ABOVE child content (children are z-index 1 inside
            the .brushed wrapper). */}
        <span className="rack-screw" style={{ top: 6,    left: 6,    "--screw-rot":  "17deg" } as React.CSSProperties} />
        <span className="rack-screw" style={{ top: 6,    right: 6,   "--screw-rot": "-32deg" } as React.CSSProperties} />
        <span className="rack-screw" style={{ bottom: 6, left: 6,    "--screw-rot":  "47deg" } as React.CSSProperties} />
        <span className="rack-screw" style={{ bottom: 6, right: 6,   "--screw-rot":   "8deg" } as React.CSSProperties} />

        {children}
      </div>
    </section>
  )
}
