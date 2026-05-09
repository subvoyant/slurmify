// ──────────────────────────────────────────────────────────────────────
// src/components/VuMeter.tsx — Audio-reactive level meter
// ──────────────────────────────────────────────────────────────────────
//
// Renders a horizontal LED-style bar that responds to playback level.
// Driven by the AnalyserNode that useFxChain taps off the dry phaser
// output (matches v0.1.6's analyser placement so the meter shows what
// the user actually HEARS, not the pre-FX dry signal).
//
// Visualisation:
//   • RMS computed from getByteTimeDomainData (a 0–255 byte stream
//     centered at 128).  RMS feels right for "perceived level" and
//     is less jumpy than peak-only readings.
//   • LED segments use the rack's identity color for "in range" and
//     a hot rose color for the top three segments ("approaching clip").
//   • Smoothing: 0.7 on the AnalyserNode itself + a one-pole IIR
//     decay in the rAF loop so the meter has a soft fall-back.
//
// rAF loop is shared across all VuMeter instances mounted on the page,
// so adding a second meter (e.g. for the input vs output) costs only
// the extra getByteTimeDomainData call, not a second animation frame.
//
// Renders as DOM rather than canvas — 24 LED segments are cheap and
// the styling integrates cleanly with the rack module aesthetic.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"

export interface VuMeterProps {
  /** AnalyserNode tapped off whatever signal you want to meter.
   *  Pass null while the FX chain is still binding — the meter
   *  silently shows zero level. */
  analyser:    AnalyserNode | null
  /** Pre-allocated buffer to read into.  Created by useFxChain
   *  alongside the analyser; reusing it across rAF avoids GC churn. */
  analyserBuf: Uint8Array | null
  /** Number of LED segments.  24 fits nicely in a single rack-row. */
  segments?:   number
  className?:  string
  /** Tooltip text override.  Default explains the meter's source. */
  tooltipText?: React.ReactNode
}

// Smoothing factor for the displayed level.  Closer to 1 = slower
// fall-back (more "VU-like" inertia).  0.85 lands around the look
// of a hardware analog meter.
const FALL_BACK = 0.85

export function VuMeter({
  analyser,
  analyserBuf,
  segments = 24,
  className,
}: VuMeterProps) {
  // Smoothed level [0..1], updated in the rAF loop and read into
  // state on every tick at ~60 Hz.  React's reconciler handles 60 Hz
  // updates fine for a 24-segment meter; if we ever push to 60+
  // segments we'd switch to a canvas.
  const [level, setLevel] = React.useState(0)

  // Hold the live level in a ref so the rAF callback can apply
  // exponential decay between samples without depending on stale
  // state from React's render cycle.
  const liveLevelRef = React.useRef(0)

  React.useEffect(() => {
    if (!analyser || !analyserBuf) return
    let raf = 0
    const tick = () => {
      analyser.getByteTimeDomainData(analyserBuf)
      // RMS computation — center samples around 0 (the buffer is
      // centered at 128) and average the squared deviations.
      let sum = 0
      for (let i = 0; i < analyserBuf.length; i++) {
        const v = (analyserBuf[i] - 128) / 128
        sum += v * v
      }
      const rms = Math.sqrt(sum / analyserBuf.length)
      // Apply soft decay so the displayed level falls back smoothly
      // even as the input drops to silence.
      const prev = liveLevelRef.current
      const next = rms > prev ? rms : prev * FALL_BACK + rms * (1 - FALL_BACK)
      liveLevelRef.current = next
      setLevel(Math.min(next, 1))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [analyser, analyserBuf])

  // Map the smoothed RMS to lit-segment count.  RMS values rarely go
  // above ~0.5 even at full-scale playback (sine wave is 0.707), so
  // we apply a soft scaling curve so the meter actually fills.
  const litCount = Math.min(
    segments,
    Math.round(Math.pow(level, 0.7) * segments * 1.4),
  )

  return (
    <div
      className={cn(
        "flex items-center gap-[2px] py-1",
        className,
      )}
      aria-hidden="true"
    >
      {Array.from({ length: segments }, (_, i) => {
        const lit = i < litCount
        // Top 3 segments use the hot color (approaching clip).
        const isHot = i >= segments - 3
        return (
          <span
            key={i}
            className={cn(
              "h-2 w-1 rounded-[1px] transition-opacity",
              lit
                ? isHot
                  ? "bg-slurm-rose opacity-100"
                  : "bg-slurm-cyan opacity-100"
                : "bg-slurm-border-2 opacity-40",
            )}
          />
        )
      })}
    </div>
  )
}
