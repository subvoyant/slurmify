// ──────────────────────────────────────────────────────────────────────
// src/components/TopBar.tsx — Sticky single-bar header chrome
// ──────────────────────────────────────────────────────────────────────
//
// Composes <PresetBar> (left) and <UtilityBar> (right) into one
// horizontal bar that sticks to the top of the viewport while the
// rack modules scroll behind it.
//
// History (W5b): pre-merge there were two separate rows directly
// underneath the SIENA SLURMER header — the preset picker on its own
// row, then the utility bar (randomize / reveal / tips / eggs / quit)
// on its own row.  Each row had its own border + bg, so the top of
// the app burned ~80 px of vertical real estate before any rack module
// even appeared.  User feedback: collapse to one compact bar that
// stays at the top even when the user scrolls down through the
// modules.  Hence this component.
//
// Layout / behaviour
// ──────────────────
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │ PRESET ▾the_real01  +save as  🗑               🎲 reveal …   │
//   │                                                              │
//   │  ─ [PresetBar contents] ──┃─ [UtilityBar contents] ──        │
//   │                  natural  ┃  flex-1; tips/eggs/quit cluster  │
//   │                  width    ┃  pinned right via internal       │
//   │                           ┃  ml-auto                         │
//   └──────────────────────────────────────────────────────────────┘
//
//   • position: sticky; top: 0 — pins to viewport when the body
//     scrolls past it.  Works because <main> in App.tsx is normal
//     flow (no overflow:hidden / overflow:auto on any ancestor),
//     so the body is the scrolling ancestor.
//
//   • z-30 — sits above rack modules (which we don't currently raise,
//     so any z-index ≥ 1 would do; 30 leaves room for a dialog/portal
//     at z-50).
//
//   • backdrop-blur-sm + 95%-opacity bg — lets a hint of the rack
//     scroll show through underneath, so the bar reads as floating
//     chrome rather than a hard divider.  If the WebKit version
//     drops backdrop-filter support the fallback is simply a solid
//     surface colour, which is fine.
//
//   • A vertical hairline (`<span class="border-l">`) separates
//     PresetBar's group from UtilityBar's so the merged-row visual
//     hierarchy still reads as "preset section | actions section"
//     rather than one undifferentiated soup of buttons.
//
// Why a wrapper rather than just inlining everything in App.tsx?
//   1. Keeps App.tsx's main render tree readable — one <TopBar />
//      replaces the previous two-row block of comments + components.
//   2. The sticky+blur+separator styling is bar-specific and would
//      bloat App.tsx.
//   3. If a future iteration moves the bar elsewhere (e.g., into the
//      header itself) the change happens here, not in App.tsx.
// ──────────────────────────────────────────────────────────────────────

import { PresetBar } from "./PresetBar"
import { UtilityBar } from "./UtilityBar"
import { cn } from "@/lib/utils"

export function TopBar() {
  return (
    <div
      className={cn(
        // Sticky positioning — top:0 anchors it to the viewport top
        // once the user scrolls past its natural position.  The body
        // (well, the outermost min-h-screen flex column in App.tsx)
        // is the scrolling ancestor, which sticky honours.
        "sticky top-0 z-30",

        // Bar shell — same surface tone as the previous two
        // separate bars, with a subtle backdrop blur so the rack
        // scrolling underneath shows through faintly.  bg/95 gives
        // the blur something to work with; without the alpha the
        // backdrop-filter is a no-op.
        "border-b border-slurm-border bg-slurm-surface/95 backdrop-blur-sm",

        // Spacing inside the bar — slightly tighter vertically than
        // the previous standalone PresetBar (which used py-2) to
        // emphasise compactness, the explicit ask in the W5b UX
        // change.  text-[11px] matches both child components'
        // existing label sizes.
        "px-3 py-1.5 text-[11px]",

        // Single horizontal flex row — children render inline.
        "flex items-center gap-3",
      )}
    >
      {/* LEFT — preset manager.  Renders flat (no inner border) per
          PresetBar's W5b-era refactor; styling lives here. */}
      <PresetBar />

      {/* Vertical hairline divider — mirrors how the rack modules
          are separated.  aria-hidden because it carries no semantic
          information; purely visual.  h-5 matches the height of the
          surrounding controls (h-7 buttons minus a couple of px so
          the line doesn't extend past the button caps). */}
      <span
        aria-hidden="true"
        className="h-5 w-px shrink-0 bg-slurm-border"
      />

      {/* RIGHT — utility actions.  UtilityBar is `flex-1` internally
          so it claims the rest of the bar; its inner `ml-auto` on
          the tips/eggs/quit group pins those buttons to the right
          edge of the bar. */}
      <UtilityBar />
    </div>
  )
}
