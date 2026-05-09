// ──────────────────────────────────────────────────────────────────────
// src/components/InOutTrimRow.tsx — Input source trim controls
// ──────────────────────────────────────────────────────────────────────
//
// Sets the [start_sec, end_sec] window of the source audio that
// slurmify will operate on.  Three buttons + two textboxes:
//
//   ┌────────────────────────────────────────────────────────────┐
//   │ in  [____1.23] [I]    out  [____4.56] [O]    [✕ clear]    │
//   └────────────────────────────────────────────────────────────┘
//
// The [I] button captures the current input-waveform playhead position
// into start_sec; [O] captures into end_sec; [✕ clear] resets both
// to 0 (= use the full file).
//
// Manual textbox edits work too — type a number, blur or press Enter
// to commit.  Values are stored as strings while editing (so partial
// "1." doesn't get clobbered to "1") and parsed/clamped on commit.
//
// end_sec=0 means "use to end of file" by convention (matches v0.1.6's
// slurmify() argument semantics).  We display 0 as empty in the
// textbox so the user sees "out: [empty] = full file" instead of a
// confusing "0".
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Scissors, X } from "lucide-react"
import { useSlurmStore } from "@/stores/slurmStore"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export interface InOutTrimRowProps {
  /** Current playhead position in seconds, from the input
   *  WaveformPlayer.  The [I] / [O] buttons capture this. */
  currentTime: number
  /** Total duration of the source audio in seconds — used to clamp
   *  out values + label the "full file" placeholder. */
  durationSec: number
  className?: string
}

/** Format seconds as "1.23" for display.  Two decimal places matches
 *  the precision of the WaveformPlayer transport's clock display. */
const fmtSec = (s: number) => s.toFixed(2)

export function InOutTrimRow({
  currentTime,
  durationSec,
  className,
}: InOutTrimRowProps) {
  const startSec        = useSlurmStore(s => s.params.start_sec)
  const endSec          = useSlurmStore(s => s.params.end_sec)
  const setParam        = useSlurmStore(s => s.setParam)
  const captureInPoint  = useSlurmStore(s => s.captureInPoint)
  const captureOutPoint = useSlurmStore(s => s.captureOutPoint)
  const clearInOut      = useSlurmStore(s => s.clearInOut)

  // Local string state for the two textboxes — lets the user type
  // partial values like "1." without snapping back to a number.
  const [startText, setStartText] = React.useState<string>(fmtSec(startSec))
  const [endText,   setEndText]   = React.useState<string>(endSec === 0 ? "" : fmtSec(endSec))

  // Sync local state when the store changes from outside (e.g.,
  // [I] / [O] / ✕ button clicks).
  React.useEffect(() => { setStartText(fmtSec(startSec)) }, [startSec])
  React.useEffect(() => { setEndText(endSec === 0 ? "" : fmtSec(endSec)) }, [endSec])

  const commitStart = () => {
    const n = parseFloat(startText)
    if (!isFinite(n) || n < 0) {
      setStartText(fmtSec(startSec))   // revert garbage
      return
    }
    const clamped = Math.min(n, durationSec)
    // Validate IN < OUT invariant.  If the typed IN would land at or
    // past OUT, refuse + revert (typed values are explicit user
    // intent — auto-correcting would feel surprising).  Capture
    // buttons + keyboard auto-correct instead; see slurmStore.
    if (endSec > 0 && clamped >= endSec) {
      setStartText(fmtSec(startSec))
      return
    }
    setParam("start_sec", clamped)
    setStartText(fmtSec(clamped))
  }
  const commitEnd = () => {
    const trimmed = endText.trim()
    if (trimmed === "") {
      setParam("end_sec", 0)   // empty = "use full file"
      return
    }
    const n = parseFloat(trimmed)
    if (!isFinite(n) || n <= 0) {
      setEndText(endSec === 0 ? "" : fmtSec(endSec))   // revert
      return
    }
    const clamped = Math.min(n, durationSec)
    // Same IN<OUT validation, mirror direction.
    if (startSec > 0 && clamped <= startSec) {
      setEndText(endSec === 0 ? "" : fmtSec(endSec))
      return
    }
    setParam("end_sec", clamped)
    setEndText(fmtSec(clamped))
  }

  // Capture-button + keyboard handlers route through the store's
  // invariant-enforcing actions (auto-correct rather than revert).
  const captureIn  = () => captureInPoint(currentTime, durationSec)
  const captureOut = () => captureOutPoint(currentTime, durationSec)
  const clearBoth  = () => clearInOut()

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        "text-[11px] text-slurm-muted",
        className,
      )}
    >
      {/* IN */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono uppercase text-[10px] tracking-wider">in</span>
        <Tip text="Start of the slurmify window in seconds. Type a value or press [I] to capture the current playhead position. 0 = start from beginning.">
          <Input
            type="number"
            min={0}
            step={0.01}
            value={startText}
            onChange={(e) => setStartText(e.target.value)}
            onBlur={commitStart}
            onKeyDown={(e) => { if (e.key === "Enter") commitStart() }}
            className="!h-6 w-20 !text-[11px]"
          />
        </Tip>
        <Tip text="Capture: set IN to the current input-waveform playhead position. Keyboard shortcut: press `i` while audio is playing (or any time the focus isn't in a textbox).">
          <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[10px]" onClick={captureIn}>
            <Scissors className="!h-3 !w-3" />
            [I]
          </Button>
        </Tip>
      </div>

      {/* OUT */}
      <div className="flex items-center gap-1.5">
        <span className="font-mono uppercase text-[10px] tracking-wider">out</span>
        <Tip text="End of the slurmify window in seconds. Empty (or 0) means run to end of file. Type a value or press [O] to capture the current playhead position.">
          <Input
            type="number"
            min={0}
            step={0.01}
            value={endText}
            onChange={(e) => setEndText(e.target.value)}
            onBlur={commitEnd}
            onKeyDown={(e) => { if (e.key === "Enter") commitEnd() }}
            placeholder={`full (${fmtSec(durationSec)})`}
            className="!h-6 w-24 !text-[11px]"
          />
        </Tip>
        <Tip text="Capture: set OUT to the current input-waveform playhead position. Keyboard shortcut: press `o` while audio is playing (or any time the focus isn't in a textbox).">
          <Button size="sm" variant="ghost" className="h-6 px-1.5 text-[10px]" onClick={captureOut}>
            <Scissors className="!h-3 !w-3" />
            [O]
          </Button>
        </Tip>
      </div>

      {/* CLEAR */}
      <Tip text="Reset IN to 0 and OUT to full-file. Slurmify will operate on the entire source.">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-1.5 text-[10px]"
          onClick={clearBoth}
          disabled={startSec === 0 && endSec === 0}
        >
          <X className="!h-3 !w-3" />
          clear
        </Button>
      </Tip>

      {/* Live indicator: window length when not full */}
      {(startSec > 0 || endSec > 0) && (
        <span className="ml-auto font-mono tabular-nums text-[10px]">
          window: {fmtSec((endSec || durationSec) - startSec)}s
        </span>
      )}
    </div>
  )
}
