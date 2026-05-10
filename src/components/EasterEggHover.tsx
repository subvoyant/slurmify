// ──────────────────────────────────────────────────────────────────────
// src/components/EasterEggHover.tsx — Reusable hover-revealed gif popup
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's CSS hover ::after pattern (ui_assets.py
// blocks 2 / 3 / 4 / 5a) to a React component.  Wraps an arbitrary
// child (button, chip, panel) and reveals an animated GIF on hover
// from one of three anchor positions:
//
//   • "spring-up"  — gif rises from BELOW the wrapped element with
//                    a bouncy cubic-bezier(0.34,1.56,0.64,1) overshoot.
//                    Used for "📁 reveal temp" (Bob, portrait) and
//                    "🎲 randomize all" (Hoberman-Max, landscape).
//
//   • "slide-in-right" — gif scales in from the RIGHT side of the
//                        wrapped element.  Used for the MAX RANDOM
//                        resolution chip (Max the tester slides in
//                        from beyond the right edge).
//
//   • "peek-up-behind" — gif sits BEHIND the wrapped element and peeks
//                        up; the element's own background must be
//                        opaque or the gif shows through the body.
//                        Used for the beat-mask strip (MaxFire pops
//                        up from behind the chip row).
//
// pointer-events: none on the gif means hovering the gif itself
// doesn't count as hovering the wrapped element — without this you
// get a flicker as the cursor enters the gif and leaves the button
// boundary.
//
// ── Portal mode ─────────────────────────────────────────────────────
// `usePortal` (recommended for any easter egg whose final position
// would be clipped by an ancestor's `overflow:hidden`) renders the
// gif into document.body via React's createPortal.  Coordinates are
// computed via getBoundingClientRect on the trigger (and optionally
// on an `alignToSelector` element) at hover-start.  The gif uses
// position:fixed in viewport coords so no ancestor clipping applies.
//
// `alignToSelector` is a CSS query string (typically
// `section[data-rack-name="stretch"]`) that anchors the gif's
// baseline to that element's top edge.  Bob uses this to land on
// stretch's header bar; MaxFire uses this so his baseline rests on
// slicing's header.
//
// ── GIF restart ─────────────────────────────────────────────────────
// Browsers cache animated GIFs by URL and resume from where playback
// last paused.  Without intervention an easter egg only "fires" once
// per session.  We append a cache-busting `?h=<counter>` query
// param that increments on each hover-start, forcing a fresh fetch
// (or at least a fresh playback) of the GIF for every hover.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { createPortal } from "react-dom"
import { cn } from "@/lib/utils"
import { useUiPrefsStore } from "@/stores/uiPrefsStore"

export type EggAnchor = "spring-up" | "slide-in-right" | "peek-up-behind"

export interface EasterEggHoverProps {
  /** The element that triggers the hover gif. */
  children:    React.ReactNode

  /** Imported gif URL (use Vite's `import gif from "..."` so the gif
   *  is hashed + bundled). */
  gifSrc:      string

  /** Width / height of the displayed gif in pixels. */
  width:       number
  height:      number

  /** Anchor style (positions the gif relative to the trigger or to
   *  the element matched by alignToSelector). */
  anchor:      EggAnchor

  /** Vertical offset in px applied AFTER the anchor positions the gif.
   *  Positive values push DOWN (in non-portal mode by adjusting the
   *  bottom coord; in portal mode by shifting the computed top). */
  offsetY?:    number

  /** When true, render the gif via createPortal into document.body
   *  with position:fixed coords computed from getBoundingClientRect
   *  on the trigger.  Use this whenever the egg's final position
   *  would land outside the trigger's nearest `overflow:hidden`
   *  ancestor (rack modules, the slicing chip strip, etc.). */
  usePortal?:  boolean

  /** CSS selector for an element that anchors the gif's baseline.
   *  Only consulted in portal mode; for spring-up and peek-up-behind
   *  the gif's BOTTOM edge is positioned at the matched element's
   *  top edge.  Example: `section[data-rack-name="stretch"]` to make
   *  Bob land on stretch's header bar. */
  alignToSelector?: string

  /** Horizontal alignment of the gif WITHIN the alignToSelector
   *  element.  Only consulted when `alignToSelector` matches AND
   *  the value is supplied; default behavior (when omitted) keeps
   *  the gif centered on the TRIGGER element regardless of the
   *  align element's bounds.
   *
   *    "left"   — gif's left edge sits 12px in from alignRect.left
   *    "center" — gif is centered horizontally on alignRect
   *    "right"  — gif's right edge sits 12px in from alignRect.right
   *
   *  Used (e.g.) so Bob can rise from the RIGHT side of the SLICING
   *  module even though his trigger button is far to the left in the
   *  utility bar. */
  alignXSide?: "left" | "center" | "right"

  /** Optional className on the outer wrapper. */
  className?:  string

  /** ARIA label for the gif (screen readers).  Default is empty so
   *  the easter egg stays purely decorative for AT users. */
  alt?:        string
}

/** Lookup table — translates an anchor name to the inline-style block
 *  that positions the gif relative to the wrapper in NON-PORTAL mode
 *  (legacy CSS-anchor positioning).  Portal mode computes coords
 *  programmatically and uses only the `bezier` + `hidden`/`shown`
 *  transforms below. */
const ANCHOR_STYLES: Record<EggAnchor, {
  base:    React.CSSProperties
  hidden:  React.CSSProperties
  shown:   React.CSSProperties
  bezier:  string
}> = {
  "spring-up": {
    base:   {
      bottom:          0,
      left:            "50%",
      transformOrigin: "bottom center",
      zIndex:          9999,
    },
    hidden: { opacity: 0, transform: "translateX(-50%) translateY(20px) scale(0.6)" },
    shown:  { opacity: 1, transform: "translateX(-50%) translateY(0) scale(1)" },
    bezier: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },

  "slide-in-right": {
    base:   {
      left:            "calc(100% + 12px)",
      bottom:          -12,
      transformOrigin: "left bottom",
      zIndex:          9999,
    },
    hidden: { opacity: 0, transform: "translateX(-12px) scale(0.55)" },
    shown:  { opacity: 1, transform: "translateX(0) scale(1)" },
    bezier: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },

  "peek-up-behind": {
    base:   {
      bottom:          "calc(100% - 18px)",
      left:            "50%",
      transformOrigin: "bottom center",
      zIndex:          0,
    },
    hidden: { opacity: 0, transform: "translateX(-50%) translateY(20px) scale(0.7)" },
    shown:  { opacity: 1, transform: "translateX(-50%) translateY(0) scale(1)" },
    bezier: "cubic-bezier(0.4, 1.2, 0.4, 1)",
  },
}

/** Compute viewport-fixed (left, top) coords for the gif in portal
 *  mode based on the active anchor + the trigger / alignTo rects.
 *  Returns coords for the gif's TOP-LEFT corner. */
function computeFixedCoords(
  anchor: EggAnchor,
  triggerRect: DOMRect,
  alignRect: DOMRect | null,
  width: number,
  height: number,
  offsetY?: number,
  alignXSide?: "left" | "center" | "right",
): { left: number; top: number } {
  // Helper — computes horizontal `left` for a gif of `width` px so
  // that the gif sits inside `alignRect` per the requested side.
  // Only used when alignToSelector matched AND alignXSide is set.
  // EDGE_INSET (12 px) keeps the gif from kissing the rack's outer
  // border so the drop-shadow has room to breathe.
  const EDGE_INSET = 12
  const horizontalFromAlign = (rect: DOMRect): number => {
    switch (alignXSide) {
      case "left":   return rect.left  + EDGE_INSET
      case "right":  return rect.right - width - EDGE_INSET
      case "center":
      default:       return rect.left  + rect.width / 2 - width / 2
    }
  }

  switch (anchor) {
    case "spring-up": {
      // Gif's BOTTOM edge sits at alignRect.top (e.g. stretch's
      // header top) when alignToSelector is provided; otherwise at
      // the trigger's bottom.
      // Horizontal placement defaults to the trigger center.  When
      // alignXSide is supplied AND alignRect matched, the gif is
      // anchored to the alignRect's left/center/right instead — this
      // lets a button in the utility bar (top-left) summon Bob to
      // rise from the SLICING module's right side without coupling
      // his X position to the button's X.
      const bottomY = alignRect ? alignRect.top : triggerRect.bottom
      const leftX =
        alignRect && alignXSide
          ? horizontalFromAlign(alignRect)
          : triggerRect.left + triggerRect.width / 2 - width / 2
      return {
        left: leftX,
        top:  bottomY - height + (offsetY ?? 0),
      }
    }
    case "peek-up-behind": {
      // Gif's BOTTOM edge sits at alignRect.top (e.g. slicing's
      // header top) when alignToSelector is provided; otherwise at
      // the trigger's TOP (so it peeks up over the trigger).
      // Same horizontal-alignment rules as spring-up.
      const bottomY = alignRect ? alignRect.top : triggerRect.top
      const leftX =
        alignRect && alignXSide
          ? horizontalFromAlign(alignRect)
          : triggerRect.left + triggerRect.width / 2 - width / 2
      return {
        left: leftX,
        top:  bottomY - height + (offsetY ?? 0),
      }
    }
    case "slide-in-right": {
      // Gif slides in from the RIGHT of the trigger.  Horizontal
      // placement is always trigger-relative — left edge sits 12 px
      // past the trigger's right edge — so the gif appears to emerge
      // out of the chip/button it belongs to.
      // Vertical placement defaults to bottom-aligned with a slight
      // downward overlap (matches the legacy `bottom: -12` anchor),
      // BUT when `alignToSelector` matches, the gif's BOTTOM edge
      // is anchored to the matched element's top edge instead.  This
      // lets Max (slide-in from MAX RANDOM chip) plant his feet on
      // the BEAT TRIM rack's top edge rather than getting cropped
      // against the resolution row above.
      // alignXSide is ignored — horizontal stays trigger-relative.
      const bottomY = alignRect ? alignRect.top : triggerRect.bottom + 12
      return {
        left: triggerRect.right + 12,
        top:  bottomY - height + (offsetY ?? 0),
      }
    }
  }
}

export function EasterEggHover({
  children,
  gifSrc,
  width,
  height,
  anchor,
  offsetY,
  usePortal = false,
  alignToSelector,
  alignXSide,
  className,
  alt = "",
}: EasterEggHoverProps) {
  // Global easter-egg-suppression toggle (UtilityBar's "eggs" button).
  // Read up-front so it joins the regular React-Hooks call order, then
  // bail out AFTER all hooks below have run — short-circuiting before
  // useState/useEffect would violate Rules of Hooks on a re-render
  // when the toggle flips.  The runtime cost of the unused hooks is
  // negligible (zustand subscription + two useState slots + an effect
  // gated on isHovering, which is false when the egg is "disabled").
  const easterEggsEnabled = useUiPrefsStore((s) => s.easterEggsEnabled)

  const [isHovering, setIsHovering] = React.useState(false)
  const wrapperRef = React.useRef<HTMLSpanElement>(null)
  const a = ANCHOR_STYLES[anchor]

  // Cache-bust counter — incremented on each hover-start so the GIF
  // URL changes (`?h=N`) and the browser fetches fresh data, which
  // restarts the animation from frame 1.  Without this an animated
  // GIF only plays once because the browser caches it after the
  // first run.
  const [bustCounter, setBustCounter] = React.useState(0)

  // Captured coords for portal mode.  Recomputed on each hover-start;
  // null when not hovering or when portal mode is off.
  const [coords, setCoords] = React.useState<{ left: number; top: number } | null>(null)

  React.useEffect(() => {
    if (!isHovering) return
    setBustCounter((c) => c + 1)

    if (usePortal && wrapperRef.current) {
      const triggerRect = wrapperRef.current.getBoundingClientRect()
      let alignRect: DOMRect | null = null
      if (alignToSelector) {
        const target = document.querySelector(alignToSelector) as HTMLElement | null
        if (target) {
          alignRect = target.getBoundingClientRect()
        }
      }
      setCoords(computeFixedCoords(anchor, triggerRect, alignRect, width, height, offsetY, alignXSide))
    }
  }, [isHovering, usePortal, alignToSelector, alignXSide, anchor, width, height, offsetY])

  // ── Easter-eggs toggle short-circuit ─────────────────────────────
  // After all hooks are wired, bail out if the user has eggs off —
  // render the child unwrapped so the underlying button/chip still
  // works exactly as before, just without the gif overlay.  Placed
  // here (not at the top of the function) to satisfy Rules of Hooks
  // even when the toggle flips mid-session.
  if (!easterEggsEnabled) {
    return <>{children}</>
  }

  // ── Build the gif's style, branching on portal vs absolute mode ──

  let gifElement: React.ReactNode

  if (usePortal && coords) {
    // Portal mode — fixed-position gif rendered into document.body.
    // No anchor base.left / .bottom needed; coords are absolute.
    const fixedStyle: React.CSSProperties = {
      position:           "fixed",
      left:               coords.left,
      top:                coords.top,
      width,
      height,
      backgroundImage:    `url(${gifSrc}?h=${bustCounter})`,
      backgroundSize:     "contain",
      backgroundRepeat:   "no-repeat",
      backgroundPosition: "bottom center",
      pointerEvents:      "none",
      transition:         `opacity 0.18s ease, transform 0.42s ${a.bezier}`,
      filter:             "drop-shadow(0 6px 16px rgba(0,0,0,0.55))",
      // Animation transforms — strip out any `translateX(-50%)` from
      // the legacy anchors since coords already place the gif's
      // top-left corner correctly.  Just animate Y + scale.
      transformOrigin:    a.base.transformOrigin,
      zIndex:             9999,
      ...(isHovering
        ? {
            opacity:   1,
            transform: anchor === "slide-in-right"
              ? "translateX(0) scale(1)"
              : "translateY(0) scale(1)",
          }
        : {
            opacity:   0,
            transform: anchor === "slide-in-right"
              ? "translateX(-12px) scale(0.55)"
              : anchor === "peek-up-behind"
                ? "translateY(20px) scale(0.7)"
                : "translateY(20px) scale(0.6)",
          }
      ),
    }
    gifElement = createPortal(
      <div style={fixedStyle} role="img" aria-label={alt} />,
      document.body,
    )
  } else {
    // Non-portal mode — legacy CSS-anchor absolute positioning.
    const offsetStyle: React.CSSProperties = {}
    if (offsetY !== undefined && a.base.bottom !== undefined) {
      const baseBottom = typeof a.base.bottom === "number" ? a.base.bottom : 0
      offsetStyle.bottom = baseBottom - offsetY
    }
    const gifStyle: React.CSSProperties = {
      position:           "absolute",
      width,
      height,
      backgroundImage:    `url(${gifSrc}?h=${bustCounter})`,
      backgroundSize:     "contain",
      backgroundRepeat:   "no-repeat",
      backgroundPosition: "bottom center",
      pointerEvents:      "none",
      transition:         `opacity 0.18s ease, transform 0.42s ${a.bezier}`,
      filter:             "drop-shadow(0 6px 16px rgba(0,0,0,0.55))",
      ...a.base,
      ...offsetStyle,
      ...(isHovering ? a.shown : a.hidden),
    }
    gifElement = (
      <span
        style={gifStyle}
        role="img"
        aria-label={alt}
      />
    )
  }

  return (
    <span
      ref={wrapperRef}
      className={cn("relative inline-block", className)}
      style={{ overflow: "visible" }}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      <span style={{ position: "relative", zIndex: 1 }}>{children}</span>
      {gifElement}
    </span>
  )
}
