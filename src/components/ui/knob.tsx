// ──────────────────────────────────────────────────────────────────────
// src/components/ui/knob.tsx — Rotary knob primitive (custom, no deps)
// ──────────────────────────────────────────────────────────────────────
//
// A rotary knob that behaves like the ones in Reason / u-he / Valhalla
// plugins.  Hand-rolled rather than pulled in via react-knob-headless
// because:
//
//   1. Full control over feel — drag sensitivity, scroll-wheel step,
//      double-click reset, fine-mode (shift+drag), keyboard semantics.
//   2. No peer-dep risk against React 19 (most knob libs still
//      list React 18 in their peerDependencies).
//   3. Pure SVG visual — easy to swap for custom painted artwork
//      later without touching the behavior layer.  Replace just the
//      <KnobVisual> component (it's purely the SVG part) and the
//      drag/keyboard/wheel logic continues to work.
//
// ── Behavior ────────────────────────────────────────────────────────
//   • Pointer drag — vertical drag (up = increase, down = decrease).
//     200px of drag = full min→max range.  Hold Shift for fine mode
//     (1000px = full range).  Pointer capture so dragging off the
//     knob still registers.
//   • Scroll wheel — up = +step, down = -step.  No accidental page
//     scroll thanks to preventDefault.
//   • Keyboard — focusable via Tab. Arrow keys = ±step. Page Up/Down
//     = ±10*step. Home/End = min/max.
//   • Double click — reset to defaultValue (if provided) or midpoint.
//   • ARIA — role="slider" with valuemin / valuemax / valuenow /
//     valuetext.  Screen readers announce value changes.
//
// ── Visual ─────────────────────────────────────────────────────────
//   • 270° sweep (from -135° to +135° measured from the top).
//   • Outer track ring (muted, full sweep)
//   • Active arc (primary color, from -135° to the current angle)
//   • Center indicator line pointing in the direction of the value
//   • Inner disc (slurm-surface) for visual depth
//
// All colors via CSS vars so skins re-tint at runtime without
// remounting.  Sizes via the `size` prop in pixels.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"

// ── Math helpers ──────────────────────────────────────────────────────
// SVG arc math — converting between value-on-a-range, normalized 0-1,
// degrees-from-top, and SVG path "d" strings.
//
// Convention: 0° is at the top of the knob; angles increase clockwise.
// The knob sweeps 270° total — from -135° (down-left) to +135° (down-
// right), leaving a 90° gap at the bottom.  This matches the standard
// hardware-plugin convention.

const SWEEP_START_DEG = -135
const SWEEP_END_DEG   = 135
const SWEEP_TOTAL_DEG = SWEEP_END_DEG - SWEEP_START_DEG   // 270

/** Convert a "0° at top, clockwise" angle in degrees to {x, y} on a
 *  circle of radius `r` centered at (cx, cy). */
function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return {
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  }
}

/** Build an SVG arc path string from `startDeg` to `endDeg` clockwise
 *  on a circle of radius `r` centered at (cx, cy).  `endDeg` should be
 *  >= `startDeg`; the result is a "M start A r r 0 large-arc 1 end"
 *  d-attribute. */
function describeArc(cx: number, cy: number, r: number, startDeg: number, endDeg: number): string {
  if (endDeg <= startDeg) return ""
  const start = polarToCartesian(cx, cy, r, startDeg)
  const end   = polarToCartesian(cx, cy, r, endDeg)
  const largeArc = endDeg - startDeg > 180 ? 1 : 0
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`
}

/** Clamp v to [lo, hi]. */
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Snap v to the nearest multiple of step (useful for quantizing
 *  during drag / wheel / keyboard interactions). */
const quantize = (v: number, step: number, min: number) =>
  step > 0 ? min + Math.round((v - min) / step) * step : v


// ── Component ─────────────────────────────────────────────────────────

export interface KnobProps {
  value:    number
  onChange: (v: number) => void

  min:  number
  max:  number
  step: number

  /** Pixel diameter of the knob.  56px is a comfortable default for
   *  rack rows; reduce to 40-48px for very dense layouts. */
  size?: number

  /** When the user double-clicks, reset to this value.  Falls back to
   *  the midpoint of the range if not provided. */
  defaultValue?: number

  /** Pixels of vertical drag = full range traversal.  Default 200.
   *  Holding Shift switches to fine mode (5× this value). */
  pixelsForFullRange?: number

  /** Disabled state — greys out + ignores all input. */
  disabled?: boolean

  /** ARIA label / valuetext.  Screen readers announce these on
   *  focus + value change.  `aria-valuetext` is what the user
   *  actually hears (formatted value); `aria-label` describes what
   *  the knob controls. */
  ariaLabel?:     string
  ariaValueText?: string

  /** Optional className for the outer wrapper. */
  className?: string
}

export const Knob = React.forwardRef<HTMLDivElement, KnobProps>(function Knob(
  {
    value,
    onChange,
    min,
    max,
    step,
    size = 56,
    defaultValue,
    pixelsForFullRange = 200,
    disabled = false,
    ariaLabel,
    ariaValueText,
    className,
  },
  forwardedRef,
) {
  const innerRef = React.useRef<HTMLDivElement>(null)
  const ref = (forwardedRef ?? innerRef) as React.RefObject<HTMLDivElement>

  // Drag state — a non-null `dragStart` means we're mid-drag.  We
  // remember (a) the pointer Y at drag start, (b) the value at drag
  // start, and (c) the active pointer ID so we can release capture.
  const dragStartRef = React.useRef<{
    pointerId: number
    startY:    number
    startVal:  number
  } | null>(null)

  // Normalized 0-1 value drives the visual.  Out-of-range values are
  // clamped purely for display — the actual `value` is whatever the
  // caller's state is (they should also clamp).
  const normalized = clamp((value - min) / (max - min || 1), 0, 1)
  const angleDeg   = SWEEP_START_DEG + normalized * SWEEP_TOTAL_DEG

  // ── Pointer (drag) ─────────────────────────────────────────────────
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    dragStartRef.current = {
      pointerId: e.pointerId,
      startY:    e.clientY,
      startVal:  value,
    }
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = dragStartRef.current
    if (!start || start.pointerId !== e.pointerId) return
    e.preventDefault()
    // Up = increase, down = decrease.  Multiply by 5 for fine mode
    // (Shift held) — gives us precise values without the user having
    // to release and re-grab.
    const fineMode = e.shiftKey
    const ppr = pixelsForFullRange * (fineMode ? 5 : 1)
    const dy = start.startY - e.clientY
    const dValue = (dy / ppr) * (max - min)
    const next = clamp(quantize(start.startVal + dValue, step, min), min, max)
    if (next !== value) onChange(next)
  }

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragStartRef.current?.pointerId === e.pointerId) {
      ;(e.target as Element).releasePointerCapture?.(e.pointerId)
      dragStartRef.current = null
    }
  }

  // ── Wheel ──────────────────────────────────────────────────────────
  // Need to attach via useEffect with passive=false to allow
  // preventDefault — React's onWheel attaches as a passive listener
  // and can't preventDefault.  Without this, scrolling a knob also
  // scrolls the page.
  React.useEffect(() => {
    const node = ref.current
    if (!node) return
    const handler = (e: WheelEvent) => {
      if (disabled) return
      e.preventDefault()
      // Wheel up = positive deltaY in old convention but most modern
      // browsers report scroll-up as NEGATIVE deltaY.  We want wheel-
      // up to INCREASE the knob, which matches scroll-up convention.
      const direction = e.deltaY < 0 ? 1 : -1
      const fineMode = e.shiftKey
      const stride   = step * (fineMode ? 1 : Math.max(1, Math.round((max - min) / step / 100)))
      const next = clamp(quantize(value + direction * stride, step, min), min, max)
      if (next !== value) onChange(next)
    }
    node.addEventListener("wheel", handler, { passive: false })
    return () => node.removeEventListener("wheel", handler)
  }, [ref, value, onChange, min, max, step, disabled])

  // ── Keyboard ───────────────────────────────────────────────────────
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    let delta = 0
    switch (e.key) {
      case "ArrowUp":
      case "ArrowRight":
        delta = step;  break
      case "ArrowDown":
      case "ArrowLeft":
        delta = -step; break
      case "PageUp":
        delta = step * 10;  break
      case "PageDown":
        delta = -step * 10; break
      case "Home":
        e.preventDefault(); onChange(min); return
      case "End":
        e.preventDefault(); onChange(max); return
      default:
        return
    }
    e.preventDefault()
    const next = clamp(quantize(value + delta, step, min), min, max)
    if (next !== value) onChange(next)
  }

  // ── Double-click reset ─────────────────────────────────────────────
  const onDoubleClick = () => {
    if (disabled) return
    const reset = defaultValue ?? (min + max) / 2
    onChange(clamp(quantize(reset, step, min), min, max))
  }

  // ── Render ─────────────────────────────────────────────────────────
  const isDragging = dragStartRef.current !== null

  return (
    <div
      ref={ref}
      role="slider"
      aria-label={ariaLabel}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={ariaValueText}
      aria-disabled={disabled}
      aria-orientation="vertical"
      tabIndex={disabled ? -1 : 0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      onDoubleClick={onDoubleClick}
      className={cn(
        "relative inline-block touch-none",
        disabled
          ? "opacity-40 pointer-events-none"
          : isDragging
            ? "cursor-grabbing"
            : "cursor-grab",
        "focus:outline-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-slurm-bg rounded-full",
        className,
      )}
      style={{ width: size, height: size }}
    >
      <KnobVisual size={size} angleDeg={angleDeg} />
    </div>
  )
})

// ── KnobVisual — pure SVG, swap with custom artwork later ────────────
// Pulled out as its own component so a future "painted knob" can
// drop in as a 1-line replacement (e.g., <KnobImage src="..."
// rotation={angleDeg} />) without touching any of the drag /
// keyboard / wheel / ARIA logic above.

function KnobVisual({ size, angleDeg }: { size: number; angleDeg: number }) {
  // viewBox is fixed 100x100 so all our math uses friendly numbers
  // regardless of pixel size.
  const cx = 50
  const cy = 50
  const trackR = 42
  const indicatorEndR = 32   // tip of the indicator line (close to outer)
  const indicatorStartR = 12 // base of the indicator line (near center)
  const indicatorTip   = polarToCartesian(cx, cy, indicatorEndR,   angleDeg)
  const indicatorBase  = polarToCartesian(cx, cy, indicatorStartR, angleDeg)

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className="overflow-visible"
    >
      {/* Outer track ring — full 270° sweep (muted) */}
      <path
        d={describeArc(cx, cy, trackR, SWEEP_START_DEG, SWEEP_END_DEG)}
        stroke="var(--slurm-border-2)"
        strokeWidth={6}
        strokeLinecap="round"
        fill="none"
      />

      {/* Active arc — from -135° to current angle, in primary */}
      <path
        d={describeArc(cx, cy, trackR, SWEEP_START_DEG, angleDeg)}
        stroke="hsl(var(--primary))"
        strokeWidth={6}
        strokeLinecap="round"
        fill="none"
      />

      {/* Inner disc — gives the knob "body" the appearance of depth */}
      <circle
        cx={cx}
        cy={cy}
        r={26}
        fill="var(--slurm-surface)"
        stroke="var(--slurm-border-2)"
        strokeWidth={1}
      />

      {/* Indicator line — points from near-center to outer rim, in
          the direction of the value.  Standard knob convention. */}
      <line
        x1={indicatorBase.x}
        y1={indicatorBase.y}
        x2={indicatorTip.x}
        y2={indicatorTip.y}
        stroke="var(--slurm-fg)"
        strokeWidth={3}
        strokeLinecap="round"
      />
    </svg>
  )
}
