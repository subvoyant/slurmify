// ──────────────────────────────────────────────────────────────────────
// src/components/KnobNoteToggle.tsx — Knob OR note-Select with ms ⇄ ♪
// toggle (Phase E3c.2; ADR-0020 frontend port)
// ──────────────────────────────────────────────────────────────────────
//
// One vertical cell that holds three states stacked top-to-bottom:
//
//   ┌─────────────────────────┐
//   │     ╭──────╮             │
//   │    (   ●   )      ← knob (when mode === "ms")
//   │     ╰──────╯             │
//   │       — OR —             │
//   │   [ 1/16  ▾ ]    ← note Select (when mode === "♪")
//   │                          │
//   │       skip               │   ← label (small caps, muted)
//   │       125 ms             │   ← value (mono, tabular)
//   │   ─────────              │
//   │   [ ms │ ♪ ]             │   ← mode toggle
//   │   ≈ 1/16 @ 126           │   ← cross-direction hint
//   └─────────────────────────┘
//
// Why a single component instead of two side-by-side cells?
//   Putting the toggle next to the knob would either widen each cell
//   significantly or require breaking onto two rows.  Stacking under
//   the value text reuses the existing 76-96px column width and keeps
//   the four musical-time knobs aligned with the non-musical ones.
//
// Live-hint behavior matches v0.1.6 (`_slurmUpdateHint` in
// ui_assets.py):
//   • mode "ms" → show closest note label at current BPM ("≈ 1/16 @ 126")
//   • mode "♪"  → show ms equivalent at current BPM ("≈ 119 ms @ 126")
//
// The slurmStore holds BOTH the ms value AND the note string per
// param; we read/write whichever is "active" based on `mode`, and
// useSlurmifyJob conditionally forwards `*_note` only when mode is
// "♪" (matches Python's _note_to_ms semantics — empty string falls
// back to the _ms value).
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Knob } from "@/components/ui/knob"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
  NOTE_LABELS,
  type NoteLabel,
  noteToMs,
  msToClosestNote,
  formatMs,
} from "@/lib/note-mode"
import { useEffectiveBpm } from "@/hooks/useEffectiveBpm"

export interface KnobNoteToggleProps {
  /** Top label, e.g. "skip", "trim start". */
  label: string

  /** ── ms-mode wiring ───────────────────────────────────────────── */
  msValue: number
  onMsChange: (v: number) => void
  msMin: number
  msMax: number
  msStep: number
  /** Default value for the knob's double-click reset.  Falls back to
   *  (min+max)/2 if omitted. */
  msDefault?: number

  /** ── ♪-mode wiring ────────────────────────────────────────────── */
  noteValue: NoteLabel | string   // string for forwards-compat with future labels
  onNoteChange: (v: NoteLabel) => void

  /** ── Mode + toggle ────────────────────────────────────────────── */
  mode: "ms" | "♪"
  onModeChange: (v: "ms" | "♪") => void

  /** Verbose tooltip — same content rules as LabeledKnob. */
  tooltip?: React.ReactNode

  /** Knob diameter.  Default 56 to match LabeledKnob. */
  size?: number

  disabled?: boolean
  className?: string
}

export function KnobNoteToggle({
  label,
  msValue,
  onMsChange,
  msMin,
  msMax,
  msStep,
  msDefault,
  noteValue,
  onNoteChange,
  mode,
  onModeChange,
  tooltip,
  size = 56,
  disabled,
  className,
}: KnobNoteToggleProps) {
  // BPM source of truth for the live hint.  Updates automatically when
  // the user types into the BPM-override textbox or when /analyze
  // populates analysis.bpm.
  const { bpm, source, detecting } = useEffectiveBpm()

  // Build the hint string + the value-display row.  Logic mirrors
  // _slurmUpdateHint in ui_assets.py.
  let hintText: string
  let valueDisplay: React.ReactNode
  if (mode === "♪") {
    const ms = noteToMs(noteValue, bpm)
    valueDisplay = (
      <>
        {ms > 0 ? formatMs(ms) : "0"}
        <span className="ml-0.5 text-slurm-muted">ms</span>
      </>
    )
    hintText = ms > 0
      ? `≈ ${formatMs(ms)} ms @ ${bpm.toFixed(0)} BPM`
      : "off"
  } else {
    valueDisplay = (
      <>
        {msValue.toFixed(0)}
        <span className="ml-0.5 text-slurm-muted">ms</span>
      </>
    )
    if (msValue > 0) {
      const closest = msToClosestNote(msValue, bpm)
      hintText = closest
        ? `≈ ${closest} @ ${bpm.toFixed(0)} BPM`
        : `@ ${bpm.toFixed(0)} BPM`
    } else {
      hintText = "off"
    }
  }
  // BPM-source suffix for the hint — only show "(detected)" / etc.
  // when it's interesting.  Suppress for the silent fallback to keep
  // the UI quiet when there's no source to reveal.
  const sourceTag = detecting
    ? " (detecting…)"
    : source === "override"
      ? " (override)"
      : source === "detected"
        ? " (detected)"
        : ""

  // Slightly wider than LabeledKnob (76 → 88) to comfortably fit the
  // hint text underneath without forced wrapping.
  const cell = (
    <div
      className={cn(
        "flex flex-col items-center gap-1",
        "w-[96px] shrink-0 select-none",
        disabled && "opacity-50",
        className,
      )}
    >
      {/* Top: knob OR note-select, depending on mode */}
      <div className="flex h-[56px] items-center justify-center">
        {mode === "ms" ? (
          <Knob
            value={msValue}
            onChange={onMsChange}
            min={msMin}
            max={msMax}
            step={msStep}
            size={size}
            defaultValue={msDefault}
            disabled={disabled}
            ariaLabel={label}
            ariaValueText={`${msValue.toFixed(0)} ms`}
          />
        ) : (
          <Select
            value={noteValue}
            onValueChange={(v) => onNoteChange(v as NoteLabel)}
            disabled={disabled}
          >
            {/* Compact trigger that fits inside the 96px cell.  The
                content panel itself uses Radix's portal so it can
                escape the cell width without truncation. */}
            <SelectTrigger className="!h-7 w-[72px] !text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {NOTE_LABELS.map((n) => (
                <SelectItem key={n} value={n} className="text-[11px]">
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Label */}
      <div className="text-[10px] uppercase tracking-[0.05em] text-slurm-muted leading-tight text-center">
        {label}
      </div>

      {/* Value display — always shows ms equivalent (so flipping
          the toggle keeps the user oriented in the same units). */}
      <div className="text-[11px] font-mono tabular-nums leading-tight text-slurm-fg">
        {valueDisplay}
      </div>

      {/* Mode toggle — two tiny chips.  Click "ms" or "♪" to switch.
          Active chip uses primary fg/bg; inactive is muted. */}
      <div
        role="tablist"
        aria-label={`${label} unit`}
        className={cn(
          "flex items-center rounded border border-slurm-border-2 bg-slurm-bg/50",
          "text-[10px] font-mono",
          "overflow-hidden",
        )}
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === "ms"}
          onClick={() => onModeChange("ms")}
          disabled={disabled}
          className={cn(
            "px-1.5 py-0.5 transition-colors",
            mode === "ms"
              ? "bg-primary/15 text-primary"
              : "text-slurm-muted hover:text-slurm-fg",
          )}
        >
          ms
        </button>
        <span className="text-slurm-border-2">|</span>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "♪"}
          onClick={() => onModeChange("♪")}
          disabled={disabled}
          className={cn(
            "px-1.5 py-0.5 transition-colors",
            mode === "♪"
              ? "bg-primary/15 text-primary"
              : "text-slurm-muted hover:text-slurm-fg",
          )}
        >
          ♪
        </button>
      </div>

      {/* Cross-direction hint — what would this be in the OTHER unit? */}
      <div className="text-[9px] text-slurm-muted text-center leading-tight tabular-nums">
        {hintText}
        {sourceTag && (
          <span className="text-slurm-border-2">{sourceTag}</span>
        )}
      </div>
    </div>
  )

  return tooltip ? <Tip text={tooltip}>{cell}</Tip> : cell
}
