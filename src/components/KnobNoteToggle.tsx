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
  formatMs,
} from "@/lib/note-mode"
import { useEffectiveBpm } from "@/hooks/useEffectiveBpm"

export interface KnobNoteToggleProps {
  /** Top label, e.g. "skip", "trim start". */
  label: string

  /** ── Linear (non-♪) mode wiring.  Historically named "ms*" because
   *  the original four callsites all measured durations in ms; now
   *  a generic value-in-some-unit knob.  See `valueUnit` /
   *  `valueModeLabel` / `noteToValue` to flip the unit. */
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
  /** Current mode.  Internally we check `!== "♪"` to identify the
   *  linear-value mode, so any non-"♪" string works (e.g., "ms",
   *  "Hz", "s"). */
  mode: string
  onModeChange: (v: string) => void

  /** ── Optional unit/conversion overrides ───────────────────────── */
  /** Mode value sent on the value-mode button click.  Default "ms".
   *  Tremolo rate, for example, passes "Hz". */
  valueMode?: string
  /** Unit string shown next to the value display ("ms" / "Hz" / etc).
   *  Default "ms". */
  valueUnit?: string
  /** Label rendered on the value-mode toggle button (the non-"♪"
   *  side).  Default "ms". */
  valueModeLabel?: string
  /** Formatter for the linear value (default = formatMs which gives
   *  0-decimal at ≥10, 1-decimal below).  Tremolo rate uses
   *  `(v) => v.toFixed(2)` to show "4.00 Hz". */
  valueFormat?: (v: number) => string
  /** Conversion from a note label + BPM to the linear-mode value
   *  unit.  Default = noteToMs (returns milliseconds).  For
   *  rate-style controls (Hz), pass
   *    `(n, bpm) => { const ms = noteToMs(n, bpm); return ms > 0 ? 1000/ms : 0 }`
   *  so a "1/4" note at 120 BPM resolves to 2 Hz instead of 500 ms. */
  noteToValue?: (note: string, bpm: number) => number

  /** Verbose tooltip — same content rules as LabeledKnob. */
  tooltip?: React.ReactNode

  /** Knob diameter.  Default 56 to match LabeledKnob. */
  size?: number

  /** Optional graticule passed through to the underlying Knob. */
  markers?: Array<{ value: number; label?: string }>

  /** Optional custom value↔normalized mappers for tapered knobs.  See
   *  Knob's KnobProps for the contract. */
  valueToNorm?: (v: number) => number
  normToValue?: (n: number) => number

  /** Where to place the ms/♪ mode toggle relative to the knob.
   *
   *    "below" (default) — vertical stack: knob → label → value →
   *      toggle → hint.  Cell is ~96 px wide, ~115 px tall.  Used by
   *      stutter `skip` where the cell sits inside a narrow column
   *      and vertical room is plentiful.
   *
   *    "right" — toggle (and hint) live in a column to the RIGHT of
   *      the knob, with label + value still centered below.  Cell is
   *      wider (~140 px) but only ~80 px tall, matching a bare
   *      LabeledKnob's height.  Used by BEAT TRIM so the rack matches
   *      STRETCH's height when the two sit side-by-side.
   */
  toggleLayout?: "below" | "right"

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
  valueMode = "ms",
  valueUnit = "ms",
  valueModeLabel = "ms",
  valueFormat,
  noteToValue,
  tooltip,
  size = 56,
  markers,
  valueToNorm,
  normToValue,
  toggleLayout = "below",
  disabled,
  className,
}: KnobNoteToggleProps) {
  // Effective conversion + format functions.  Defaults preserve the
  // original "ms" behavior so the four existing slurmify callsites
  // (stutter skip, beat trim start/end, beat gap) work unchanged.
  const fmt: (v: number) => string = valueFormat ?? formatMs
  const n2v: (n: string, b: number) => number = noteToValue ?? noteToMs

  // Closest-note helper that uses the supplied n2v.  Replaces the
  // hard-coded msToClosestNote so the cross-direction hint works
  // for any unit (ms duration → closest 1/N, OR Hz rate → closest
  // 1/N at the current BPM).
  const valueToClosestNote = (value: number, bpm: number): NoteLabel | "" => {
    if (!Number.isFinite(value) || value <= 0) return ""
    if (!Number.isFinite(bpm)   || bpm   <= 0) return ""
    let best: NoteLabel | "" = ""
    let bestDelta = Infinity
    for (const note of NOTE_LABELS) {
      const v = n2v(note, bpm)
      if (!Number.isFinite(v) || v <= 0) continue
      const delta = Math.abs(v - value)
      if (delta < bestDelta) {
        bestDelta = delta
        best = note
      }
    }
    return best
  }
  // BPM source of truth for the live hint.  Updates automatically when
  // the user types into the BPM-override textbox or when /analyze
  // populates analysis.bpm.
  const { bpm, source, detecting } = useEffectiveBpm()

  // Build the hint string + the value-display row.  Generic across
  // ms / Hz / arbitrary-unit knobs — the noteToValue function and
  // the unit string are all that change between use cases.
  let hintText: string
  let valueDisplay: React.ReactNode
  if (mode === "♪") {
    const v = n2v(noteValue, bpm)
    valueDisplay = (
      <>
        {v > 0 ? fmt(v) : "0"}
        <span className="ml-0.5 text-slurm-muted">{valueUnit}</span>
      </>
    )
    hintText = v > 0
      ? `≈ ${fmt(v)} ${valueUnit} @ ${bpm.toFixed(0)} BPM`
      : "off"
  } else {
    valueDisplay = (
      <>
        {fmt(msValue)}
        <span className="ml-0.5 text-slurm-muted">{valueUnit}</span>
      </>
    )
    if (msValue > 0) {
      const closest = valueToClosestNote(msValue, bpm)
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

  // ── Reusable sub-elements — both layouts share these pieces ──
  // Extracting them keeps the two layout branches readable and means
  // a tweak to (e.g.) the toggle styling lands once, not twice.

  const knobOrSelect = (
    // Top: knob OR note-select, depending on mode.  The non-"♪"
    // side is the LINEAR-VALUE mode — its name comes in via the
    // `mode` prop (could be "ms", "Hz", etc).  We check
    // `mode !== "♪"` rather than `mode === "ms"` so the same
    // component supports any linear unit.
    <div className="flex h-[56px] items-center justify-center">
      {mode !== "♪" ? (
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
          ariaValueText={`${fmt(msValue)} ${valueUnit}`}
          markers={markers}
          valueToNorm={valueToNorm}
          normToValue={normToValue}
        />
      ) : (
        <Select
          value={noteValue}
          onValueChange={(v) => onNoteChange(v as NoteLabel)}
          disabled={disabled}
        >
          {/* Compact trigger that fits inside the cell.  The
              content panel uses Radix's portal so it can escape
              the cell width without truncation. */}
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
  )

  const labelEl = (
    <div className="text-[10px] uppercase tracking-[0.05em] text-slurm-muted leading-tight text-center">
      {label}
    </div>
  )

  const valueEl = (
    // Value display — always shows the active-mode equivalent (so
    // flipping the toggle keeps the user oriented in the same units).
    <div className="text-[11px] font-mono tabular-nums leading-tight text-slurm-fg">
      {valueDisplay}
    </div>
  )

  const toggleEl = (
    // Mode toggle — two tiny chips.  Click "ms" or "♪" to switch.
    // Active chip uses primary fg/bg; inactive is muted.
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
        aria-selected={mode !== "♪"}
        onClick={() => onModeChange(valueMode)}
        disabled={disabled}
        className={cn(
          "px-1.5 py-0.5 transition-colors",
          mode !== "♪"
            ? "bg-primary/15 text-primary"
            : "text-slurm-muted hover:text-slurm-fg",
        )}
      >
        {valueModeLabel}
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
  )

  const hintEl = (
    // Cross-direction hint — what the value would be in the OTHER
    // unit.  Same content for both layouts, just placed differently.
    <div className="text-[9px] text-slurm-muted leading-tight tabular-nums">
      {hintText}
      {sourceTag && (
        <span className="text-slurm-border-2">{sourceTag}</span>
      )}
    </div>
  )

  // ── Cell — assembled per layout ──────────────────────────────────
  // "below"  → 96 px wide × ~115 px tall, vertical stack (legacy default)
  // "right"  → 140 px wide × ~80 px tall, knob-row over label/value
  //   so the cell matches a plain LabeledKnob's height.

  let cell: React.ReactNode
  if (toggleLayout === "right") {
    cell = (
      <div
        className={cn(
          "flex flex-col items-center gap-1",
          "w-[140px] shrink-0 select-none",
          disabled && "opacity-50",
          className,
        )}
      >
        {/* Knob on the left, toggle + hint stacked in a column on
            the right.  items-start aligns the right column to the
            top of the knob so the toggle pill sits at the same
            height as the knob's top edge — visually balanced. */}
        <div className="flex h-[56px] items-start gap-2">
          {knobOrSelect}
          <div className="flex flex-col items-start gap-1 pt-1">
            {toggleEl}
            {hintEl}
          </div>
        </div>
        {labelEl}
        {valueEl}
      </div>
    )
  } else {
    // Default "below" layout — slightly wider than LabeledKnob
    // (76 → 96) to comfortably fit the hint text underneath without
    // forced wrapping.
    cell = (
      <div
        className={cn(
          "flex flex-col items-center gap-1",
          "w-[96px] shrink-0 select-none",
          disabled && "opacity-50",
          className,
        )}
      >
        {knobOrSelect}
        {labelEl}
        {valueEl}
        {toggleEl}
        {/* The hintEl variant centers its text in the "below" layout. */}
        <div className="text-[9px] text-slurm-muted text-center leading-tight tabular-nums">
          {hintText}
          {sourceTag && (
            <span className="text-slurm-border-2">{sourceTag}</span>
          )}
        </div>
      </div>
    )
  }

  return tooltip ? <Tip text={tooltip}>{cell}</Tip> : cell
}
