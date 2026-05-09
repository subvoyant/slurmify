// ──────────────────────────────────────────────────────────────────────
// src/components/EasterEggHover.tsx — Reusable hover-revealed gif popup
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's CSS hover ::after pattern (ui_assets.py
// blocks 2 / 3 / 4 / 5a) to a React component.  Wraps an arbitrary
// child (button, chip, panel) and reveals an animated GIF on hover
// from one of four anchor positions:
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
// All anchors share the same fade-in transition; the spring anchors
// add the overshoot bezier curve for the playful spring feel.
//
// pointer-events: none on the gif means hovering the gif itself
// doesn't count as hovering the wrapped element — without this you
// get a flicker as the cursor enters the gif and leaves the button
// boundary.
//
// z-index 9999 keeps the gif above sibling rack modules and the
// rest of the page chrome.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"

export type EggAnchor = "spring-up" | "slide-in-right" | "peek-up-behind"

export interface EasterEggHoverProps {
  /** The element that triggers the hover gif.  Wrapped in a relative
   *  container so absolute positioning works against it.  Pass a
   *  Button, chip, or panel — anything that responds to :hover. */
  children:    React.ReactNode

  /** Imported gif URL (use Vite's `import gif from "..."` so the gif
   *  is hashed + bundled). */
  gifSrc:      string

  /** Width / height of the displayed gif in pixels.  v0.1.6 picked
   *  these per-gif to preserve the aspect ratio of the source files. */
  width:       number
  height:      number

  /** Anchor position relative to the wrapped element. */
  anchor:      EggAnchor

  /** Optional className on the outer wrapper. */
  className?:  string

  /** ARIA label for the gif (screen readers).  Default is empty so
   *  the easter egg stays purely decorative for AT users. */
  alt?:        string
}

/**
 * Lookup table — translates an anchor name to the inline-style block
 * that positions the gif relative to the wrapper.  Keeping this as
 * an object literal (vs a switch in the JSX) lets us share a single
 * <span> render path for all anchors.
 */
const ANCHOR_STYLES: Record<EggAnchor, {
  base:    React.CSSProperties
  hidden:  React.CSSProperties
  shown:   React.CSSProperties
  bezier:  string
}> = {
  // Spring up from below — Bob + Hoberman-Max.  Anchored at the
  // bottom of the wrapper, transform-origin bottom center, starts 20px
  // lower scaled to 0.6 then springs to natural position.
  "spring-up": {
    base:   {
      bottom:          0,
      left:            "50%",
      transformOrigin: "bottom center",
      zIndex:          9999,
    },
    hidden: {
      opacity:   0,
      transform: "translateX(-50%) translateY(20px) scale(0.6)",
    },
    shown:  {
      opacity:   1,
      transform: "translateX(-50%) translateY(0) scale(1)",
    },
    bezier: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },

  // Slide in from the right edge — Max for MAX RANDOM.  Anchored just
  // past the right edge, scales from 0.55 to 1.
  "slide-in-right": {
    base:   {
      left:            "calc(100% + 12px)",
      bottom:          -12,
      transformOrigin: "left bottom",
      zIndex:          9999,
    },
    hidden: {
      opacity:   0,
      transform: "translateX(-12px) scale(0.55)",
    },
    shown:  {
      opacity:   1,
      transform: "translateX(0) scale(1)",
    },
    bezier: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },

  // Peek up from behind — MaxFire on the beat mask.  Anchored ABOVE
  // the wrapper (so the gif is visible peeking over the top edge),
  // sitting BEHIND the wrapper visually via z-index 0 (vs the wrapper
  // contents at z-index 1).  Starts hidden 30px lower scaled to 0.7.
  "peek-up-behind": {
    base:   {
      bottom:          "calc(100% - 18px)",   // 18px overlap so it peeks
      left:            "50%",
      transformOrigin: "bottom center",
      zIndex:          0,                     // BEHIND the wrapper content
    },
    hidden: {
      opacity:   0,
      transform: "translateX(-50%) translateY(20px) scale(0.7)",
    },
    shown:  {
      opacity:   1,
      transform: "translateX(-50%) translateY(0) scale(1)",
    },
    bezier: "cubic-bezier(0.4, 1.2, 0.4, 1)",
  },
}

export function EasterEggHover({
  children,
  gifSrc,
  width,
  height,
  anchor,
  className,
  alt = "",
}: EasterEggHoverProps) {
  const [isHovering, setIsHovering] = React.useState(false)
  const a = ANCHOR_STYLES[anchor]

  // Combined gif style — base anchor + hidden/shown state interpolated
  // via CSS transitions.  Inline rather than CSS-class because the
  // `bottom`/`left`/`transform-origin` triplet is per-anchor and
  // expressing that as 3 utility classes is messier than one object.
  const gifStyle: React.CSSProperties = {
    position:        "absolute",
    width,
    height,
    backgroundImage:    `url(${gifSrc})`,
    backgroundSize:     "contain",
    backgroundRepeat:   "no-repeat",
    backgroundPosition: "bottom center",
    pointerEvents:      "none",
    transition:         `opacity 0.18s ease, transform 0.42s ${a.bezier}`,
    filter:             "drop-shadow(0 6px 16px rgba(0,0,0,0.55))",
    ...a.base,
    ...(isHovering ? a.shown : a.hidden),
  }

  return (
    <span
      className={cn("relative inline-block", className)}
      // Allow the gif to escape the wrapper.  All anchors rely on
      // absolute positioning beyond the wrapper bounds, so any
      // ancestor with `overflow:hidden` would clip them — we don't
      // own those ancestors here, but at least the immediate wrapper
      // has explicit `overflow:visible`.
      style={{ overflow: "visible" }}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {/* Wrapper content — keep at z-index 1 so it sits above the
          peek-up-behind gif but below the spring/slide gifs. */}
      <span style={{ position: "relative", zIndex: 1 }}>{children}</span>
      {/* The gif itself — always rendered, just hidden via opacity
          when not hovering.  This is how the v0.1.6 CSS ::after
          worked: the GIF was always loaded, only its opacity changed
          on hover.  Same trade-off here: ~0.5 MB upfront vs 200ms
          delay on first hover. */}
      <span
        style={gifStyle}
        role="img"
        aria-label={alt}
      />
    </span>
  )
}
