// ──────────────────────────────────────────────────────────────────────
// src/components/Dancer.tsx — Siena dancer GIF shown during processing
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's "loading dancer" pattern (slurm_ui.py
// build_ui section).  In v0.1.6 the dancer was a Gradio Image that
// flipped between visible=False and visible=True via the click chain;
// here we render only when the slurmify (or burn-fx, or render-video)
// job is in flight.
//
// Unlike v0.1.6 — which had ONE Gradio image flipped on/off — we
// render the Dancer wherever a long-running job lives:
//   • OUTPUT module while slurmify is running
//   • FX module while burn-fx is running
//   • VIDEO module while render-video is running
//
// Sized to the v0.1.6 width=200 default, but accepts an override so
// callers can shrink it for tighter rack rows (FX module's burn
// progress, for instance, doesn't need a 200px tall dancer).
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { cn } from "@/lib/utils"

// Vite import — bundled with a hashed filename in production.  Path
// is relative from src/components/ to <project>/assets/.
import dancerGif from "../../assets/siena_dancer.gif"

export interface DancerProps {
  /** Width of the dancer image in pixels.  Default 200 matches
   *  v0.1.6's gr.Image(width=200). */
  width?:     number
  /** Optional caption shown beneath the dancer.  Default null = no
   *  caption.  Useful for putting the current job's `desc` field
   *  (e.g. "Detecting beats…", "Stretching audio…") right next to
   *  the animation. */
  caption?:   React.ReactNode
  className?: string
}

/**
 * Render the Siena dancer GIF.  Caller is responsible for gating
 * visibility — typically wrapped in `{isRunning && <Dancer />}`.
 *
 * The img element loads the gif lazily via Vite's hashed URL; once
 * loaded the GIF loops indefinitely (browsers don't cap loop count
 * unless the GIF metadata says so, and siena_dancer.gif's metadata
 * specifies infinite).
 */
export function Dancer({ width = 200, caption, className }: DancerProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-1.5",
        "select-none",
        className,
      )}
    >
      <img
        src={dancerGif}
        alt="Siena dancing"
        width={width}
        // height auto preserves the gif's aspect ratio without forcing
        // us to know it at compile time.
        className="rounded"
        // Disable the browser's image context menu — easter egg, not
        // a downloadable asset.
        draggable={false}
      />
      {caption && (
        <div className="text-[11px] tabular-nums text-slurm-muted">
          {caption}
        </div>
      )}
    </div>
  )
}
