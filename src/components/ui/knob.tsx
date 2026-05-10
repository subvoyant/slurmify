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

  /** Optional custom value↔normalized-position mappers.  When BOTH
   *  are supplied, the knob's drag/wheel/keyboard math + the
   *  indicator-arc rotation use these instead of linear scaling.
   *  Use for log/exponential tapers (e.g., FX ring-sweep rate where
   *  0.001–1 Hz should occupy 70 % of the knob travel and 1–20 Hz
   *  the remaining 30 %).
   *
   *  Both functions must be inverses of each other and clamp into
   *  their respective domains:
   *    valueToNorm(min) === 0
   *    valueToNorm(max) === 1
   *    normToValue(0)   === min
   *    normToValue(1)   === max
   *
   *  When provided, `step` is interpreted as a normalized fraction
   *  (default 0.005) for keyboard/wheel increments rather than
   *  raw value delta — otherwise the increment-per-key would be
   *  wildly non-uniform across a log range. */
  valueToNorm?: (v: number) => number
  normToValue?: (n: number) => number

  /** Optional graticule — tick marks + small labels printed around
   *  the outside of the knob's outer ring at the given values.
   *  Useful for log-tapered knobs where a number readout alone
   *  doesn't communicate "where 1 Hz lives on this knob".  Each
   *  marker's angle is computed via the active value↔norm mapper,
   *  so tapered knobs get correctly-spaced ticks automatically.
   *
   *  Example:
   *    markers={[
   *      { value: 0,  label: "0" },
   *      { value: 1,  label: "1" },
   *      { value: 20, label: "∞" },
   *    ]}
   */
  markers?: Array<{ value: number; label?: string }>

  /** When true (and `defaultValue` is provided), auto-renders an
   *  unlabeled tick at the default position.  Used on FX knobs that
   *  have a "unity" / passthrough state (gain at 0 dB, depth at 0,
   *  mix at 0, tone at 0) so the user can find center at a glance.
   *  Tick is rendered slightly thicker than user `markers` and in
   *  a brighter shade so it's distinguishable. */
  showDefaultMark?: boolean

  /** When true, the active (primary-color) arc fills from the SWEEP
   *  END toward the indicator instead of from the SWEEP START.
   *  Pair with an inverted `valueToNorm` so a knob whose VALUE
   *  grows as the indicator moves CCW (e.g., the panner's L
   *  control where 1 = full left and the indicator points left)
   *  shows a FULLY-LIT arc at max value rather than an empty one.
   *  At value=0 the indicator sits at the SWEEP END (CW) and the
   *  arc has zero length; as the value grows the indicator rotates
   *  CCW and the arc grows toward it from the end. */
  invertArc?: boolean

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
    valueToNorm,
    normToValue,
    markers,
    showDefaultMark,
    invertArc,
    className,
  },
  forwardedRef,
) {
  const innerRef = React.useRef<HTMLDivElement>(null)
  const ref = (forwardedRef ?? innerRef) as React.RefObject<HTMLDivElement>

  // Drag state — a non-null `dragStart` means we're mid-drag.  We
  // remember (a) the pointer Y at drag start, (b) the NORMALIZED
  // value at drag start (0-1), and (c) the active pointer ID so we
  // can release capture.  Storing the normalized value lets the drag
  // math operate uniformly across linear and tapered knobs — pixels
  // map to normalized-position delta, which we convert back to a
  // value via normToValue (or linear math for the default taper).
  const dragStartRef = React.useRef<{
    pointerId:  number
    startY:     number
    startNorm:  number
  } | null>(null)

  // Resolve the active value↔norm mappers.  Custom tapers must be
  // both-or-nothing; if only one is supplied we fall back to linear
  // (the assumption is the caller forgot to pair them).
  const usingCustomTaper = !!(valueToNorm && normToValue)
  const v2n = (v: number): number =>
    usingCustomTaper ? valueToNorm!(v) : (v - min) / (max - min || 1)
  const n2v = (n: number): number =>
    usingCustomTaper ? normToValue!(n) : min + n * (max - min)

  // Normalized 0-1 value drives the visual.  Out-of-range values are
  // clamped purely for display — the actual `value` is whatever the
  // caller's state is (they should also clamp).
  const normalized = clamp(v2n(value), 0, 1)
  const angleDeg   = SWEEP_START_DEG + normalized * SWEEP_TOTAL_DEG

  // ── Pointer (drag) ─────────────────────────────────────────────────
  // We do all drag math in NORMALIZED space (0..1) so linear and
  // tapered knobs feel identical at the pointer level.  pixels of
  // dy → fraction of full norm range → new norm → new value via the
  // active mappers.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    e.preventDefault()
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    dragStartRef.current = {
      pointerId: e.pointerId,
      startY:    e.clientY,
      startNorm: clamp(v2n(value), 0, 1),
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
    const dNorm = dy / ppr
    const newNorm = clamp(start.startNorm + dNorm, 0, 1)
    const rawNext = n2v(newNorm)
    // For linear knobs, quantize to step.  For custom-taper knobs,
    // quantizing in raw value space would clobber the curve's fine
    // resolution at low values, so we skip step quantization there
    // (the underlying float still settles to a clean number).
    const next = usingCustomTaper
      ? clamp(rawNext, min, max)
      : clamp(quantize(rawNext, step, min), min, max)
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
      let next: number
      if (usingCustomTaper) {
        // Stride in normalized space — 1 % of the knob travel per
        // notch, 0.2 % when fine mode is held.
        const dNorm = direction * (fineMode ? 0.002 : 0.01)
        const newNorm = clamp(v2n(value) + dNorm, 0, 1)
        next = clamp(n2v(newNorm), min, max)
      } else {
        const stride = step * (fineMode ? 1 : Math.max(1, Math.round((max - min) / step / 100)))
        next = clamp(quantize(value + direction * stride, step, min), min, max)
      }
      if (next !== value) onChange(next)
    }
    node.addEventListener("wheel", handler, { passive: false })
    return () => node.removeEventListener("wheel", handler)
  }, [ref, value, onChange, min, max, step, disabled])

  // ── Keyboard ───────────────────────────────────────────────────────
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    // For custom-taper knobs, increments are in normalized space so
    // each keypress moves the same VISUAL distance regardless of
    // where on the curve we are.  For linear knobs, increments are
    // in value units (the historical behavior).
    let dValue = 0     // linear-mode delta
    let dNorm  = 0     // taper-mode delta
    switch (e.key) {
      case "ArrowUp":
      case "ArrowRight":
        dValue = step;        dNorm =  0.01;  break
      case "ArrowDown":
      case "ArrowLeft":
        dValue = -step;       dNorm = -0.01;  break
      case "PageUp":
        dValue = step * 10;   dNorm =  0.10;  break
      case "PageDown":
        dValue = -step * 10;  dNorm = -0.10;  break
      case "Home":
        e.preventDefault(); onChange(min); return
      case "End":
        e.preventDefault(); onChange(max); return
      default:
        return
    }
    e.preventDefault()
    let next: number
    if (usingCustomTaper) {
      const newNorm = clamp(v2n(value) + dNorm, 0, 1)
      next = clamp(n2v(newNorm), min, max)
    } else {
      next = clamp(quantize(value + dValue, step, min), min, max)
    }
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
      <KnobVisual
        size={size}
        angleDeg={angleDeg}
        markers={markers}
        defaultMarkValue={
          showDefaultMark && defaultValue !== undefined
            ? defaultValue
            : undefined
        }
        valueToAngleDeg={(v) => SWEEP_START_DEG + clamp(v2n(v), 0, 1) * SWEEP_TOTAL_DEG}
        invertArc={invertArc}
      />
    </div>
  )
})

// ── KnobVisual — pure SVG, swap with custom artwork later ────────────
// Pulled out as its own component so a future "painted knob" can
// drop in as a 1-line replacement (e.g., <KnobImage src="..."
// rotation={angleDeg} />) without touching any of the drag /
// keyboard / wheel / ARIA logic above.

function KnobVisual({
  size,
  angleDeg,
  markers,
  defaultMarkValue,
  valueToAngleDeg,
  invertArc,
}: {
  size: number
  angleDeg: number
  markers?: Array<{ value: number; label?: string }>
  /** When provided, render a SINGLE distinguished tick at this
   *  value's knob position to indicate the "default / unity" state.
   *  Slightly brighter + thicker than user markers so it stands out. */
  defaultMarkValue?: number
  valueToAngleDeg?: (v: number) => number
  invertArc?: boolean
}) {
  // viewBox is fixed 100x100 so all our math uses friendly numbers
  // regardless of pixel size.
  const cx = 50
  const cy = 50
  const trackR = 44

  // Indicator line — runs from the inner disc edge (radius 14) to
  // the outer rim (radius 32) so it's a substantial pip rather than
  // a hairline.  Gradient is built with a tip-glow effect so the
  // tip catches the rack's color.
  const indicatorEndR   = 33
  const indicatorStartR = 14
  const indicatorTip   = polarToCartesian(cx, cy, indicatorEndR,   angleDeg)
  const indicatorBase  = polarToCartesian(cx, cy, indicatorStartR, angleDeg)

  // Generate per-instance unique IDs for the gradient defs so multiple
  // knobs on the same page don't collide on `url(#knobFace)`.
  const idBase = React.useId().replace(/:/g, "")

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className="overflow-visible"
    >
      <defs>
        {/* Knob face gradient — radial, centered slightly UP-LEFT so
            the highlight position simulates light from above-left
            (matches the same convention as the corner-screw highlights).
            Stops: bright at 0%, mid-shadow at 70%, deep edge at 100%. */}
        <radialGradient
          id={`${idBase}-face`}
          cx="35%" cy="30%" r="75%"
        >
          <stop offset="0%"   stopColor="rgba(255,255,255,0.18)" />
          <stop offset="35%"  stopColor="rgba(255,255,255,0.04)" />
          <stop offset="65%"  stopColor="rgba(0,0,0,0.20)" />
          <stop offset="100%" stopColor="rgba(0,0,0,0.55)" />
        </radialGradient>

        {/* Outer rim metallic ring — runs around the body of the knob
            to fake a brushed-aluminum bezel.  Conic isn't widely
            available in SVG; we approximate with a vertical linear
            gradient that catches "highlights" at top + bottom. */}
        <linearGradient
          id={`${idBase}-rim`}
          x1="0" y1="0" x2="0" y2="1"
        >
          <stop offset="0%"   stopColor="rgba(255,255,255,0.35)" />
          <stop offset="50%"  stopColor="rgba(80,80,80,0.10)" />
          <stop offset="100%" stopColor="rgba(0,0,0,0.55)" />
        </linearGradient>

        {/* Indicator gradient — bright at the tip, fades toward the
            base.  Tip color is the primary so it picks up the active
            skin's accent. */}
        <linearGradient
          id={`${idBase}-ind`}
          x1={indicatorBase.x.toString()} y1={indicatorBase.y.toString()}
          x2={indicatorTip.x.toString()}  y2={indicatorTip.y.toString()}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%"   stopColor="var(--slurm-fg)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="hsl(var(--primary))" />
        </linearGradient>

        {/* Drop shadow under the knob body — gives the "raised disc"
            feel.  blurred, offset slightly down. */}
        <filter id={`${idBase}-drop`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.5" />
          <feOffset dy="1.5" />
          <feComponentTransfer><feFuncA type="linear" slope="0.55" /></feComponentTransfer>
          <feMerge>
            <feMergeNode />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Soft glow filter for the active arc + indicator tip so the
            value reads as illuminated. */}
        <filter id={`${idBase}-glow`} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="1.2" />
          <feMerge>
            <feMergeNode />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Default-mark tick — single distinguished tick rendered at
          the knob's "default / unity" position when provided.
          Heavier stroke + slightly brighter color than user markers
          so the user can find center at a glance.  Useful on
          unity-state knobs (gain at 0 dB, depth at 0, mix at 0). */}
      {defaultMarkValue !== undefined && valueToAngleDeg && (() => {
        const a  = valueToAngleDeg(defaultMarkValue)
        const p1 = polarToCartesian(cx, cy, 47, a)
        const p2 = polarToCartesian(cx, cy, 53, a)
        return (
          <line
            x1={p1.x} y1={p1.y}
            x2={p2.x} y2={p2.y}
            stroke="var(--slurm-fg)"
            strokeWidth={1.5}
            strokeLinecap="round"
            opacity={0.55}
            aria-hidden="true"
          />
        )
      })()}

      {/* Optional graticule — tick marks + small numeric labels
          printed AROUND the outside of the outer ring at user-
          supplied values.  Renders in the SVG underneath the track
          ring so the active arc still draws on top.  Marker angles
          go through valueToAngleDeg so log-tapered knobs get
          correctly-spaced ticks (e.g., the ring-sweep "1 Hz" tick
          ends up at 70 % of the knob travel rather than 5 %).
          Tick line: from r=48 to r=52 (just OUTSIDE the trackR=44).
          Label: at r=58, rotated to face outward.  We keep the
          viewBox at 100×100 — markers just live in the svg's
          overflow:visible region. */}
      {markers && valueToAngleDeg && (
        <g aria-hidden="true">
          {markers.map((m, i) => {
            const a   = valueToAngleDeg(m.value)
            const p1  = polarToCartesian(cx, cy, 48, a)
            const p2  = polarToCartesian(cx, cy, 53, a)
            const lp  = polarToCartesian(cx, cy, 60, a)
            return (
              <g key={i}>
                <line
                  x1={p1.x} y1={p1.y}
                  x2={p2.x} y2={p2.y}
                  stroke="var(--slurm-muted)"
                  strokeWidth={1}
                  strokeLinecap="round"
                  opacity={0.7}
                />
                {m.label && (
                  <text
                    x={lp.x}
                    y={lp.y}
                    fill="var(--slurm-muted)"
                    fontSize="9"
                    fontFamily="VT323, monospace"
                    textAnchor="middle"
                    dominantBaseline="middle"
                  >
                    {m.label}
                  </text>
                )}
              </g>
            )
          })}
        </g>
      )}

      {/* Outer track ring — full 270° sweep, muted.  Slightly thicker
          than v0 so the active arc can sit clearly on top of it. */}
      <path
        d={describeArc(cx, cy, trackR, SWEEP_START_DEG, SWEEP_END_DEG)}
        stroke="var(--slurm-border-2)"
        strokeWidth={5}
        strokeLinecap="round"
        fill="none"
      />

      {/* Active arc — fills from one of the sweep endpoints to the
          current indicator angle, in primary, with a soft glow
          filter so it reads as backlit.  Direction is determined
          by `invertArc`:
            • normal:    SWEEP_START_DEG → angleDeg (CCW end → indicator)
            • inverted:  angleDeg → SWEEP_END_DEG  (indicator → CW end)
          The inverted form is used by knobs whose value GROWS as
          the indicator rotates CCW (e.g., the panner's L control)
          so the lit arc still grows with the value. */}
      <path
        d={
          invertArc
            ? describeArc(cx, cy, trackR, angleDeg, SWEEP_END_DEG)
            : describeArc(cx, cy, trackR, SWEEP_START_DEG, angleDeg)
        }
        stroke="hsl(var(--primary))"
        strokeWidth={5}
        strokeLinecap="round"
        fill="none"
        filter={`url(#${idBase}-glow)`}
      />

      {/* Outer rim ring — sits OUTSIDE the active arc so the active
          arc visually overlaps it slightly.  Adds depth around the
          edge of the knob body. */}
      <circle
        cx={cx} cy={cy} r={37}
        fill="none"
        stroke={`url(#${idBase}-rim)`}
        strokeWidth={2}
      />

      {/* Knob body — solid disc with the radial face gradient on top.
          Two shapes layered: the base disc (solid color so the
          gradient stops are honest), then the gradient overlay. */}
      <circle
        cx={cx} cy={cy} r={31}
        fill="var(--slurm-surface)"
        stroke="rgba(0,0,0,0.55)"
        strokeWidth={1}
        filter={`url(#${idBase}-drop)`}
      />
      <circle
        cx={cx} cy={cy} r={31}
        fill={`url(#${idBase}-face)`}
        stroke="none"
      />

      {/* Top-edge highlight arc — a very thin curved highlight on the
          upper left of the knob body, simulates the "shine" on a
          painted aluminum knob.  Sits over the face gradient. */}
      <path
        d={describeArc(cx, cy, 28, -100, -30)}
        stroke="rgba(255,255,255,0.16)"
        strokeWidth={1.5}
        strokeLinecap="round"
        fill="none"
      />

      {/* Indicator line — gradient stroke (muted at base → primary at
          tip), wider than v0 (3.5px) so the pip reads at small sizes.
          Glow filter on the line itself so the tip area picks up the
          active arc's color. */}
      <line
        x1={indicatorBase.x}
        y1={indicatorBase.y}
        x2={indicatorTip.x}
        y2={indicatorTip.y}
        stroke={`url(#${idBase}-ind)`}
        strokeWidth={3.5}
        strokeLinecap="round"
        filter={`url(#${idBase}-glow)`}
      />

      {/* Indicator tip cap — a tiny circle at the very tip in primary
          color, gives the pip a clear endpoint that catches the eye. */}
      <circle
        cx={indicatorTip.x}
        cy={indicatorTip.y}
        r={1.8}
        fill="hsl(var(--primary))"
      />
    </svg>
  )
}
