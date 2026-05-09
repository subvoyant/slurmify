// ──────────────────────────────────────────────────────────────────────
// src/components/WaveformPlayer.tsx — @wavesurfer/react integration
// ──────────────────────────────────────────────────────────────────────
//
// Wraps `useWavesurfer` from @wavesurfer/react so the rest of the app
// can render an interactive waveform with `<WaveformPlayer url="..." />`.
//
// Behaviors:
//   • Click anywhere on the waveform to seek.
//   • Drag the cursor to scrub.
//   • Spacebar play/pause when focused.
//   • Tight transport bar below: play/pause + currentTime / total +
//     "loading…" hint until isReady.
//
// Skin-aware: waveColor / progressColor / cursorColor reference our
// CSS variables, so changing the skin re-tints the waveform without
// remounting it.  WaveSurfer 7+ resolves CSS var() values inside
// color props correctly.
//
// ART-EXTENSION POINTS for later:
//   • The bar style (barWidth, barGap, barRadius) is the obvious
//     visual surface — easy to swap to a different render mode
//     ("smooth" wave, FFT spectrogram, etc.).
//   • The transport bar is plain shadcn Button + a few spans; the
//     play/pause icons are lucide.  Replace icons with custom art
//     by swapping the lucide imports.
//
// CRITICAL — the bound <audio> element is one-shot for Web Audio
// (ADR-0003 carries forward).  Phase E (W4) will bind the FX chain
// to wavesurfer.getMediaElement() exactly once.  Don't re-create the
// WaveformPlayer just to reload audio — useWavesurfer handles URL
// changes by reusing the same audio element.
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from "react"
import { useWavesurfer } from "@wavesurfer/react"
import { Pause, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tip } from "@/components/ui/tooltip"
import { cn, formatTime } from "@/lib/utils"
import { useSkinColors } from "@/hooks/useSkinColors"

interface WaveformPlayerProps {
  /** URL of the audio file to render.  When this changes, wavesurfer
   *  reloads in place (no remount needed). */
  url: string
  /** Pixel height of the waveform render area.  Default 80 fits in a
   *  rack module body with room for the transport bar below. */
  height?: number
  /** Optional callback fired whenever the playhead moves (drag, play,
   *  or seek).  Used by the in/out trim controls in the INPUT module
   *  to capture the current playback position. */
  onTimeUpdate?: (currentTime: number) => void
  /** Optional callback fired ONCE when wavesurfer's underlying
   *  HTMLMediaElement is first available.  The OUTPUT module's
   *  useFxChain hook binds Web Audio nodes to this element.  Per
   *  ADR-0003 the binding is one-shot per element — wavesurfer
   *  reuses the same <audio> across URL changes, so binding once
   *  is correct.  Don't use this prop on the INPUT player — that
   *  audio is for trim selection, not FX preview. */
  onMediaElement?: (el: HTMLMediaElement) => void
  /** Optional className for the outer wrapper. */
  className?: string
}

export function WaveformPlayer({
  url,
  height = 80,
  onTimeUpdate,
  onMediaElement,
  className,
}: WaveformPlayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  // ── Skin-aware colors ─────────────────────────────────────────────
  // WaveSurfer's canvas can't resolve CSS var() references.  We read
  // the actual computed hex values via getComputedStyle and re-read
  // when the skin changes, then push them into the wavesurfer
  // instance via setOptions (no remount needed).
  const colors = useSkinColors()

  // useWavesurfer creates the wavesurfer instance on first render and
  // updates it in place when props change.  Color props use the
  // resolved hex strings from useSkinColors (NOT var() refs — those
  // don't work inside canvas).
  const { wavesurfer, isReady, isPlaying, currentTime } = useWavesurfer({
    container:     containerRef,
    url,
    height,
    waveColor:     colors.cyan,
    progressColor: colors.orange,
    cursorColor:   colors.rose,
    cursorWidth:   1,
    // Bar-style render (vs continuous wave).  Matches v0.1.6's look.
    barWidth:      2,
    barGap:        1,
    barRadius:     1,
    // normalize=true means peaks are scaled so the loudest sample
    // touches the top of the canvas — gives quiet recordings a
    // visible waveform without manual gain.  Doesn't change playback
    // amplitude, only the visual.
    normalize:     true,
    // Backend issued audio with HTTP range support; let the browser
    // handle range requests for seek-without-refetch.
    backend:       "MediaElement",
    // Don't autoplay — user clicks the play button.
    autoplay:      false,
  })

  // ── Reskin the existing wavesurfer instance when colors change ──
  // Without this, the colors set above are baked at first mount and
  // skin switches don't update the canvas.  setOptions reapplies the
  // color props and triggers a redraw without recreating the
  // underlying audio element (so playback state survives).
  useEffect(() => {
    if (!wavesurfer) return
    wavesurfer.setOptions({
      waveColor:     colors.cyan,
      progressColor: colors.orange,
      cursorColor:   colors.rose,
    })
  }, [wavesurfer, colors])

  // ── Forward playhead position to caller (for in/out trim capture) ──
  // wavesurfer exposes useWavesurfer's currentTime as a smoothed
  // animation-frame value, but ALSO fires native events (audioprocess,
  // seeking, click).  We listen to those + emit on every currentTime
  // change so the parent can react instantly to seek + play.
  useEffect(() => {
    if (!onTimeUpdate) return
    onTimeUpdate(currentTime)
  }, [onTimeUpdate, currentTime])

  // ── Surface the underlying <audio> element for FX binding ─────────
  // wavesurfer's MediaElement backend creates an <audio> tag inside
  // its render tree.  The FX chain (useFxChain) needs a stable handle
  // to that element so it can call createMediaElementSource exactly
  // once (ADR-0003).  We fire onMediaElement only ONCE per element
  // identity — wavesurfer reuses the same element across URL changes,
  // so a re-fire would mean either nothing (same element, idempotent
  // hook) or an unexpected element swap (panic).
  const lastReportedEl = useRef<HTMLMediaElement | null>(null)
  useEffect(() => {
    if (!onMediaElement || !wavesurfer) return
    const el = wavesurfer.getMediaElement()
    if (el && el !== lastReportedEl.current) {
      lastReportedEl.current = el
      onMediaElement(el)
    }
  }, [onMediaElement, wavesurfer, isReady])

  const totalDuration = wavesurfer?.getDuration() ?? 0

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* Waveform render area — wavesurfer mounts a <div> child
          containing its <canvas> here. */}
      <div
        ref={containerRef}
        className={cn(
          "w-full rounded border border-slurm-border-2 bg-slurm-bg/50",
          "overflow-hidden",
        )}
        style={{ minHeight: height }}
      />

      {/* Transport bar — single dense row with play/pause + time. */}
      <div className="flex items-center gap-2 text-[11px]">
        <Tip
          text={
            isPlaying
              ? "Pause playback. Spacebar also works when the waveform is focused."
              : "Play / pause the audio. Click anywhere on the waveform above to seek."
          }
        >
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0"
            onClick={() => wavesurfer?.playPause()}
            disabled={!isReady}
          >
            {isPlaying
              ? <Pause className="!h-3.5 !w-3.5" />
              : <Play  className="!h-3.5 !w-3.5" />}
          </Button>
        </Tip>

        <Tip text="Current playback position / total duration">
          <span className="flex items-baseline gap-2">
            <span className="font-mono tabular-nums text-slurm-fg cursor-help">
              {formatTime(currentTime)}
            </span>
            <span className="text-slurm-muted">/</span>
            <span className="font-mono tabular-nums text-slurm-muted">
              {formatTime(totalDuration)}
            </span>
          </span>
        </Tip>

        {!isReady && (
          <span className="ml-auto text-slurm-muted">
            decoding waveform…
          </span>
        )}
      </div>
    </div>
  )
}
