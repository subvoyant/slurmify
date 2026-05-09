// ──────────────────────────────────────────────────────────────────────
// src/App.tsx — top-level layout (Phase E1: first end-to-end slurm)
// ──────────────────────────────────────────────────────────────────────
//
// Phase E1 adds three new rack modules:
//   • SLICING   — resolution chip row (the most identity-shaping param)
//   • STRETCH   — speed slider
//   • OUTPUT    — slurmify button + progress + output waveform
//
// With these in place you can drop a track, set speed + resolution,
// hit SLURMIFY, and play back the result.  Phases E2/E3 add the
// remaining controls (envelope, transient, pitch, stutter family,
// beat trim/gap, beat mask, BPM override, in/out trim, seed).
//
// Module color identities follow docs/UI_DESIGN_BRIEF.md §9:
//   INPUT   — orange (warm I/O)
//   SLICING — teal
//   STRETCH — sand
//   OUTPUT  — LED green
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react"
import { Download, Film, Flame, Loader2, RotateCcw, RotateCw, Save, Sparkles } from "lucide-react"
import { cn } from "./lib/utils"
import { useBackend, type BackendStatus } from "./hooks/useBackend"
import { useSkinStore } from "./stores/skinStore"
import { useSlurmStore, type AnalysisResult } from "./stores/slurmStore"
import { useFxStore } from "./stores/fxStore"
import { useVideoStore } from "./stores/videoStore"
import { useBackendUrl } from "./hooks/useBackendUrl"
import { useSlurmifyJob } from "./hooks/useSlurmifyJob"
import { useBurnFxJob } from "./hooks/useBurnFxJob"
import { useFxChain } from "./hooks/useFxChain"
import { useRenderVideoJob } from "./hooks/useRenderVideoJob"
import { api, invalidateBackendUrl } from "./lib/api"
import { saveBackendFileAs, audioFilter, mp4Filter } from "./lib/save-as"
import { VuMeter } from "./components/VuMeter"
import { Dancer } from "./components/Dancer"

import { SkinPicker } from "./components/SkinPicker"
import { Button } from "./components/ui/button"
import { Progress } from "./components/ui/progress"

import { DropZone } from "./components/DropZone"
import { RackModule } from "./components/RackModule"
import { WaveformPlayer } from "./components/WaveformPlayer"
import { LabeledSelect } from "./components/LabeledSelect"
import { LabeledSwitch } from "./components/LabeledSwitch"
import { LabeledKnob } from "./components/LabeledKnob"
import { LabeledTextbox } from "./components/LabeledTextbox"
import { KnobToggle } from "./components/KnobToggle"
import { KnobNoteToggle } from "./components/KnobNoteToggle"
import type { NoteLabel } from "./lib/note-mode"
import { ResolutionPicker, type Resolution } from "./components/ResolutionPicker"
import { BeatMaskStrip } from "./components/BeatMaskStrip"
import { InOutTrimRow } from "./components/InOutTrimRow"
import { UtilityBar } from "./components/UtilityBar"
import { PresetBar } from "./components/PresetBar"
import { Tip } from "./components/ui/tooltip"

export function App() {
  const status = useBackend()
  const sourceFile = useSlurmStore(s => s.sourceFile)

  // Belt-and-suspenders: ensure data-skin matches the persisted store on
  // mount, in case rehydration ran before the DOM was ready.
  const skin = useSkinStore(s => s.skin)
  useEffect(() => {
    document.documentElement.dataset.skin = skin
  }, [skin])

  const hasSource = !!sourceFile

  return (
    <div className="flex min-h-screen flex-col bg-slurm-bg text-slurm-fg">
      {/* ── Header ────────────────────────────────────────────────── */}
      <header
        className={cn(
          "flex items-center justify-between gap-3",
          "border-b border-slurm-border bg-slurm-surface",
          "px-4 py-2",
        )}
      >
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-extralight tracking-[0.2em] text-slurm-cyan">
            SIENA SLURMER
          </h1>
          <span className="text-[11px] uppercase tracking-[0.2em] text-slurm-muted">
            v0.2.0
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ConnectionIndicator status={status} />
          <SkinPicker />
        </div>
      </header>

      {/* ── Main rack ─────────────────────────────────────────────── */}
      <main className="flex flex-1 flex-col gap-2 p-3">
        {/* Preset bar — saved slurmify flavors (factory + user).
            Lives above all rack modules so picking a preset is
            visibly an "everything updates at once" action rather
            than tied to any single module. */}
        <PresetBar />

        {/* Utility bar — randomize-all dice + reveal-temp folder */}
        {hasSource && (
          <UtilityBar />
        )}

        {/* INPUT module */}
        <RackModule
          color="input"
          name="input"
          status={hasSource ? "active" : "idle"}
          badge={hasSource ? "loaded" : "empty"}
        >
          <SourceModuleBody />
        </RackModule>

        {/* SLICING module — gated behind a source being loaded.
            Showing controls before there's audio to apply them to is
            UX clutter. */}
        {hasSource && (
          <RackModule color="slicing" name="slicing" status="idle">
            <SlicingBody />
          </RackModule>
        )}

        {/* STRETCH module — same gating */}
        {hasSource && (
          <RackModule color="stretch" name="stretch" status="idle">
            <StretchBody />
          </RackModule>
        )}

        {/* BEAT TRIM module — per-slice trim + gap */}
        {hasSource && (
          <RackModule color="trim" name="beat trim" status="idle">
            <BeatTrimBody />
          </RackModule>
        )}

        {/* STUTTER module — stutter family + reverse */}
        {hasSource && (
          <RackModule color="stutter" name="stutter" status="idle">
            <StutterBody />
          </RackModule>
        )}

        {/* OUTPUT module — slurmify button + progress + result.
            The OUTPUT player is also the FX preview player (single-
            player rule from the design brief).  Web Audio binds to
            its underlying <audio> element via useFxChain; knob
            changes in the FX module below show up in the playback
            instantly. */}
        {hasSource && (
          <OutputModule />
        )}

        {/* FX module — distortion, ring mod, delay, phaser.  Sits
            below OUTPUT so the user follows the audio flow visually
            (slurmify → output player → FX layer → speakers). */}
        {hasSource && (
          <RackModule color="fx" name="fx" status="idle">
            <FxBody />
          </RackModule>
        )}

        {/* VIDEO module — render YouTube-ready 1920×1080 MP4 with the
            slurmify loop animation + the audio (dry slurm or burned
            FX, auto-resolved).  Self-describing PATCH JSON metadata
            atom (ADR-0008) means the file is fully reproducible. */}
        {hasSource && (
          <RackModule color="video" name="video export" status="idle">
            <VideoBody />
          </RackModule>
        )}

        {/* Phase tracker — drops once W3 lands */}
        <div
          className={cn(
            "rounded border border-slurm-border bg-slurm-surface",
            "px-3 py-2",
            "text-[11px] leading-relaxed text-slurm-muted",
          )}
        >
          Week 5 — video export + dancer + Bob + Max ×3 easter eggs.{" "}
          <span className="text-slurm-rose">
            Next: W6 — code signing, notarization, DMG, v0.2.0 release.
          </span>
        </div>
      </main>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// SourceModuleBody (unchanged from D2)
// ──────────────────────────────────────────────────────────────────────

function SourceModuleBody() {
  const sourceFile     = useSlurmStore(s => s.sourceFile)
  const clearSource    = useSlurmStore(s => s.clearSource)
  const captureInPoint  = useSlurmStore(s => s.captureInPoint)
  const captureOutPoint = useSlurmStore(s => s.captureOutPoint)
  const setAnalysis    = useSlurmStore(s => s.setAnalysis)
  const backendUrl     = useBackendUrl()

  // Local state for the input waveform's playhead position — used
  // by the in/out trim controls below.  WaveformPlayer forwards
  // its currentTime via onTimeUpdate.
  const [currentTime, setCurrentTime] = useState(0)

  // ── Trigger BPM analysis once the source loads ────────────────────
  // /analyze runs librosa.beat.beat_track on the file and caches the
  // result on the backend.  We fire it immediately after the upload
  // completes so the SLICING module's "detected BPM" hint and the
  // ms ⇄ ♪ note-mode toggles (Phase E3c.2) have a real number to use
  // instead of falling back to the 120 default.
  //
  // The fetch is fire-and-forget: failure (e.g., backend offline,
  // librosa exception) leaves analysis === null, and the SLICING
  // module just shows "—" for the detected BPM.  The user can still
  // type a manual BPM override or run slurmify; the engine's own beat
  // detection runs independently inside slurmcore.detect_slice_points.
  //
  // The cancel flag prevents a stale response from clobbering a newer
  // file's analysis if the user replaces the source mid-fetch.
  useEffect(() => {
    if (!sourceFile) return
    let cancelled = false
    void (async () => {
      try {
        const result = await api<AnalysisResult>(`/analyze/${sourceFile.file_id}`)
        if (!cancelled) setAnalysis(result)
      } catch (err) {
        // Soft-fail — log and leave analysis null.  The UI gracefully
        // degrades to "BPM unknown" rather than throwing.
        // eslint-disable-next-line no-console
        console.warn("[slurm] /analyze failed:", err)
      }
    })()
    return () => { cancelled = true }
  }, [sourceFile, setAnalysis])

  // Keyboard shortcuts — `i` / `o` capture the current playhead
  // position into start_sec / end_sec respectively.  Matches v0.1.6
  // (and most DAWs).  Skips when focus is in a textbox / textarea /
  // contenteditable so users can still type the letters i/o into
  // the BPM-override / seed / in-out fields.
  //
  // Routes through the slurmStore's captureInPoint / captureOutPoint
  // actions so the IN < OUT invariant is enforced — see slurmStore
  // for the auto-correction rules.
  useEffect(() => {
    if (!sourceFile) return
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toUpperCase()
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) {
        return
      }
      if (e.key === "i" || e.key === "I") {
        e.preventDefault()
        captureInPoint(currentTime, sourceFile.duration_sec)
      } else if (e.key === "o" || e.key === "O") {
        e.preventDefault()
        captureOutPoint(currentTime, sourceFile.duration_sec)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [currentTime, sourceFile, captureInPoint, captureOutPoint])

  if (!sourceFile) {
    return <DropZone />
  }

  const fileUrl = backendUrl
    ? `${backendUrl}/files/${sourceFile.file_id}`
    : null

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3 text-[11px]">
        <span className="font-medium text-slurm-fg">{sourceFile.name}</span>
        <span className="text-slurm-muted">·</span>
        <span className="font-mono tabular-nums text-slurm-muted">
          {sourceFile.duration_sec.toFixed(2)}s
        </span>
        <span className="text-slurm-muted">·</span>
        <span className="text-slurm-muted">
          {sourceFile.channels === 2 ? "stereo" : "mono"} · {sourceFile.sample_rate} Hz · {sourceFile.format}
        </span>
        {sourceFile.was_extracted && (
          <span className="rounded bg-slurm-orange/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-slurm-orange">
            extracted
          </span>
        )}
        <span className="ml-auto">
          <Tip text="Clear the loaded source and return to the drop zone. Any unsaved slurm outputs are discarded.">
            <Button size="sm" variant="ghost" onClick={clearSource}>
              replace
            </Button>
          </Tip>
        </span>
      </div>

      {fileUrl ? (
        <WaveformPlayer
          url={fileUrl}
          height={80}
          onTimeUpdate={setCurrentTime}
        />
      ) : (
        <div className="grid h-20 place-items-center rounded border border-slurm-border-2 bg-slurm-bg/50 text-[10px] uppercase tracking-wider text-slurm-muted">
          connecting to backend…
        </div>
      )}

      {/* In/out trim — limits which window of the source slurmify
          operates on.  Use [I] / [O] buttons to capture playhead. */}
      <InOutTrimRow
        currentTime={currentTime}
        durationSec={sourceFile.duration_sec}
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// SLICING module body — Phase E1: resolution chip row only.
// Phase E2 adds: transient_sensitivity slider, envelope_ms slider.
// Phase E3 adds: BPM override textbox, beat mask chip strip.
// ──────────────────────────────────────────────────────────────────────

function SlicingBody() {
  const resolution            = useSlurmStore((s) => s.params.resolution)
  const transientSensitivity  = useSlurmStore((s) => s.params.transient_sensitivity)
  const envelopeMs            = useSlurmStore((s) => s.params.envelope_ms)
  const randomizeOrder        = useSlurmStore((s) => s.params.randomize_order)
  const beatMask              = useSlurmStore((s) => s.params.beat_mask)
  const bpmOverride           = useSlurmStore((s) => s.params.bpm_override)
  const analysis              = useSlurmStore((s) => s.analysis)
  const setParam              = useSlurmStore((s) => s.setParam)

  // Effective BPM the live note-mode hint and Phase E3c.2 should use:
  //   1. user-supplied override (textbox)   — takes priority
  //   2. librosa detection from /analyze    — auto-detected on load
  //   3. (caller falls back to 120 if both null)
  // We expose just the *display* string here; full priority resolution
  // lives in the note-mode helper that consumes it (Phase E3c.2).
  const detectedBpm = analysis?.bpm ?? null
  const detectedBpmLabel: string =
    analysis === null
      ? "(detecting…)"
      : detectedBpm === null
        ? "(no estimate)"
        : `${detectedBpm.toFixed(1)} BPM`

  // BPM override is stored as `number | null` in the slurm store but
  // edited as a string in the textbox so the user can type partial
  // values + clear the field.  We sync from the store on change and
  // commit (parse + clamp) on blur / Enter.
  const [bpmText, setBpmText] = useState<string>(
    bpmOverride === null ? "" : String(bpmOverride)
  )
  useEffect(() => {
    setBpmText(bpmOverride === null ? "" : String(bpmOverride))
  }, [bpmOverride])
  const commitBpm = () => {
    const trimmed = bpmText.trim()
    if (trimmed === "") {
      setParam("bpm_override", null)
      return
    }
    const n = parseFloat(trimmed)
    if (isFinite(n) && n > 0) {
      const clamped = Math.min(Math.max(n, 20), 400)   // sensible BPM range
      setParam("bpm_override", clamped)
      setBpmText(String(clamped))
    } else {
      setBpmText(bpmOverride === null ? "" : String(bpmOverride))   // revert
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {/* Resolution chip row — same layout as a LabeledSlider but
          with the chip strip in the slider's place. */}
      <div className="flex items-center gap-3 py-1">
        <Tip
          text={
            <>
              How densely to slice the audio relative to detected
              beats. <strong>1/4</strong> = one slice per beat (most
              musical). <strong>1/16</strong> = four per beat
              (default — the canonical slurm tempo).{" "}
              <strong>MAX RANDOM</strong> ignores the grid entirely
              and picks slice durations from a trimodal stutter /
              chop / held distribution.
            </>
          }
        >
          <label className={cn(
            "w-32 shrink-0 text-[12px] text-slurm-muted",
            "select-none cursor-help underline decoration-dotted decoration-slurm-border-2 underline-offset-4",
          )}>
            resolution
          </label>
        </Tip>
        <ResolutionPicker
          value={resolution as Resolution}
          onChange={(r) => {
            setParam("resolution", r)
            // Beat mask chip count differs across resolutions
            // (1/4 → 4 chips, 1/16 → 16 chips, etc.).  Reset to
            // null whenever resolution changes — old mask wouldn't
            // translate meaningfully.
            setParam("beat_mask", null)
            // ADR-0013: selecting MAX RANDOM auto-checks the
            // shuffle box.  v0.1.6 implements this in slurm_ui.py;
            // we mirror the rule here on the frontend.
            if (r === "MAX RANDOM" && !randomizeOrder) {
              setParam("randomize_order", true)
            }
          }}
        />
      </div>

      {/* Bottom row — knob trio on the LEFT, beat mask on the RIGHT.
          The beat mask grid (8 cols × 1-4 rows depending on resolution)
          sits next to the knobs rather than above them, using
          horizontal real estate that was previously empty. */}
      <div className="flex flex-wrap items-start gap-6 pt-1">
        {/* Knob group — fixed width so beat mask claims the rest */}
        <div className="flex flex-wrap gap-3">
          <LabeledKnob
            label="transient"
            value={transientSensitivity}
            onChange={(v) => setParam("transient_sensitivity", v)}
            min={0} max={1} step={0.05}
            defaultValue={0.5}
            formatValue={(v) => v.toFixed(2)}
            tooltip={
              <>
                How strongly the slicer pulls grid points toward audio
                onsets (drum hits, note attacks).{" "}
                <strong>0</strong> = pure tempo grid.{" "}
                <strong>1</strong> = pure onset detection.
              </>
            }
          />
          <LabeledKnob
            label="envelope"
            value={envelopeMs}
            onChange={(v) => setParam("envelope_ms", v)}
            min={0} max={20} step={0.5}
            defaultValue={2}
            formatValue={(v) => v.toFixed(1)}
            unit="ms"
            tooltip={
              <>
                Linear fade-in/out at each slice edge.{" "}
                <strong>0 ms</strong> = classic clicky slurm.{" "}
                <strong>2-5 ms</strong> = smooth, no clicks.
              </>
            }
          />
          <KnobToggle
            label="shuffle"
            checked={randomizeOrder}
            onCheckedChange={(v) => setParam("randomize_order", v)}
            tooltip={
              <>
                Play slices in <strong>random order</strong> instead of
                their original sequence. Auto-enabled when MAX RANDOM
                is selected (chaos pairs with chaos).
              </>
            }
          />
        </div>

        {/* Beat mask — sits to the right of the knob group.  At 1/4
            it's a single short row; at 1/32 it's four rows of 8.
            The component itself is `w-fit` so it doesn't stretch. */}
        <BeatMaskStrip
          resolution={resolution}
          mask={beatMask}
          onChange={(m) => setParam("beat_mask", m)}
        />
      </div>

      {/* BPM override — optional textbox.  Set if librosa detects
          the wrong tempo octave.  Also drives the note-mode
          conversion (Phase E3c.2) for the four musical-time
          knobs.  Empty = auto-detect (default).
          Hint line shows the live-detected value from /analyze so the
          user can compare their override against what librosa picked
          (and decide whether to override at all). */}
      <LabeledTextbox
        label="BPM override"
        value={bpmText}
        onChange={setBpmText}
        onBlur={commitBpm}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur() }}
        type="number"
        min={20}
        max={400}
        step={1}
        placeholder="auto-detect"
        unit="bpm"
        inputWidth="6rem"
        tooltip={
          <>
            Override the auto-detected tempo. Leave blank for librosa's
            estimate (the default). Set explicitly if the slicer locks
            onto the wrong octave (e.g., detects 70 BPM on a 140 BPM
            track). Range: 20–400. Also drives the ♪ → ms conversion
            for the four musical-time knobs in stutter / beat trim.
          </>
        }
        hint={
          bpmOverride === null
            ? <>auto-detected: <span className="font-mono tabular-nums text-slurm-fg">{detectedBpmLabel}</span></>
            : <>override active — detected was <span className="font-mono tabular-nums">{detectedBpmLabel}</span></>
        }
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// STRETCH module body — Phase E1: speed slider only.
// Phase E2 adds: pitch_shift_semitones, preserve_pitch toggle.
// ──────────────────────────────────────────────────────────────────────

function StretchBody() {
  const speed         = useSlurmStore((s) => s.params.speed)
  const preservePitch = useSlurmStore((s) => s.params.preserve_pitch)
  const pitchShift    = useSlurmStore((s) => s.params.pitch_shift_semitones)
  const setParam      = useSlurmStore((s) => s.setParam)

  return (
    <div className="flex flex-wrap gap-3 pt-1">
      <LabeledKnob
        label="speed"
        value={speed}
        onChange={(v) => setParam("speed", v)}
        min={0.05} max={4.0} step={0.05}
        defaultValue={2.0}
        formatValue={(v) => v.toFixed(2)}
        unit="×"
        tooltip={
          <>
            Playback speed multiplier applied BEFORE slicing.{" "}
            <strong>2.0</strong> = the canonical slurm.{" "}
            <strong>0.5</strong> = half speed.
            Double-click resets to 2.0.
          </>
        }
      />
      <LabeledKnob
        label="pitch"
        value={pitchShift}
        onChange={(v) => setParam("pitch_shift_semitones", v)}
        min={-24} max={24} step={1}
        defaultValue={0}
        formatValue={(v) => (v > 0 ? `+${v}` : String(v))}
        unit="st"
        tooltip={
          <>
            Pitch shift in semitones, AFTER the speed change.
            ±12 = one octave. ±24 = two. Works best with "preserve
            pitch" ON. Double-click resets to 0.
          </>
        }
      />
      <KnobToggle
        label="preserve"
        checked={preservePitch}
        onCheckedChange={(v) => setParam("preserve_pitch", v)}
        tooltip={
          <>
            <strong>On</strong> (default): rubberband time-stretch —
            speed changes, pitch stays.{" "}
            <strong>Off</strong>: simple resample → chipmunk effect at
            high speed, monster voice at low speed.
          </>
        }
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// BEAT TRIM module — beat_trim_start_ms, beat_trim_end_ms, beat_gap_ms.
// Phase E3 wires the ms ⇄ ♪ note-mode toggle (ADR-0020) to each row.
// ──────────────────────────────────────────────────────────────────────

function BeatTrimBody() {
  const trimStart      = useSlurmStore((s) => s.params.beat_trim_start_ms)
  const trimEnd        = useSlurmStore((s) => s.params.beat_trim_end_ms)
  const beatGap        = useSlurmStore((s) => s.params.beat_gap_ms)
  const trimStartNote  = useSlurmStore((s) => s.params.beat_trim_start_note)
  const trimEndNote    = useSlurmStore((s) => s.params.beat_trim_end_note)
  const beatGapNote    = useSlurmStore((s) => s.params.beat_gap_note)
  const trimStartMode  = useSlurmStore((s) => s.params.beat_trim_start_mode)
  const trimEndMode    = useSlurmStore((s) => s.params.beat_trim_end_mode)
  const beatGapMode    = useSlurmStore((s) => s.params.beat_gap_mode)
  const setParam       = useSlurmStore((s) => s.setParam)

  return (
    <div className="flex flex-wrap gap-3 pt-1">
      <KnobNoteToggle
        label="trim start"
        msValue={trimStart}
        onMsChange={(v) => setParam("beat_trim_start_ms", v)}
        msMin={0} msMax={500} msStep={5}
        msDefault={0}
        noteValue={trimStartNote}
        onNoteChange={(v: NoteLabel) => setParam("beat_trim_start_note", v)}
        mode={trimStartMode}
        onModeChange={(m) => setParam("beat_trim_start_mode", m)}
        tooltip={
          <>
            Removes the first N ms (or one note value) of every slice
            BEFORE the envelope is applied. Kills the attack transient
            — gives a "late-entry" feel. Toggle <strong>ms ⇄ ♪</strong>
            to switch units; in ♪ mode the trim length is recomputed
            from the detected BPM at slurmify time so it always lines
            up with the slice grid (ADR-0020).
          </>
        }
      />
      <KnobNoteToggle
        label="trim end"
        msValue={trimEnd}
        onMsChange={(v) => setParam("beat_trim_end_ms", v)}
        msMin={0} msMax={500} msStep={5}
        msDefault={0}
        noteValue={trimEndNote}
        onNoteChange={(v: NoteLabel) => setParam("beat_trim_end_note", v)}
        mode={trimEndMode}
        onModeChange={(m) => setParam("beat_trim_end_mode", m)}
        tooltip={
          <>
            Removes the last N ms (or one note value) of every slice.
            Shortens decay / tail. Higher = tighter, staccato. In
            ♪ mode the value is BPM-locked: a "1/16" trim end always
            equals one 16th-note no matter the file's tempo.
          </>
        }
      />
      <KnobNoteToggle
        label="beat gap"
        msValue={beatGap}
        onMsChange={(v) => setParam("beat_gap_ms", v)}
        msMin={0} msMax={3600} msStep={10}
        msDefault={0}
        noteValue={beatGapNote}
        onNoteChange={(v: NoteLabel) => setParam("beat_gap_note", v)}
        mode={beatGapMode}
        onModeChange={(m) => setParam("beat_gap_mode", m)}
        tooltip={
          <>
            Inserts N ms (or one note value) of silence BETWEEN every
            slice after slicing. 10–50 ms = staccato pocket. 500+ ms
            = isolated beats with audible space. In ♪ mode you can
            pick rhythmic values like "1/4" for a beat-aligned pocket.
          </>
        }
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// STUTTER module — stutter family + reverse_chance.
// Phase E3 wires the ms ⇄ ♪ note-mode toggle (ADR-0020) to skip length.
// ──────────────────────────────────────────────────────────────────────

function StutterBody() {
  const stutterChance   = useSlurmStore((s) => s.params.stutter_chance)
  const stutterSkip     = useSlurmStore((s) => s.params.stutter_skip_ms)
  const stutterSkipNote = useSlurmStore((s) => s.params.stutter_skip_note)
  const stutterSkipMode = useSlurmStore((s) => s.params.stutter_skip_mode)
  const stutterReps     = useSlurmStore((s) => s.params.stutter_max_reps)
  const stutterSpread   = useSlurmStore((s) => s.params.stutter_spread)
  const reverseChance   = useSlurmStore((s) => s.params.reverse_chance)
  const setParam        = useSlurmStore((s) => s.setParam)

  return (
    <div className="flex flex-wrap gap-3 pt-1">
      <LabeledKnob
        label="chance"
        value={stutterChance}
        onChange={(v) => setParam("stutter_chance", v)}
        min={0} max={1} step={0.05}
        defaultValue={0}
        formatValue={(v) => v.toFixed(2)}
        tooltip={
          <>
            Probability that each slice is stuttered (repeated).{" "}
            <strong>0</strong> = no stutter ever.{" "}
            <strong>0.5</strong> = roughly half. <strong>1</strong>{" "}
            = every slice stutters.
          </>
        }
      />
      <KnobNoteToggle
        label="skip"
        msValue={stutterSkip}
        onMsChange={(v) => setParam("stutter_skip_ms", v)}
        msMin={0} msMax={500} msStep={5}
        msDefault={0}
        noteValue={stutterSkipNote}
        onNoteChange={(v: NoteLabel) => setParam("stutter_skip_note", v)}
        mode={stutterSkipMode}
        onModeChange={(m) => setParam("stutter_skip_mode", m)}
        tooltip={
          <>
            How far back into each slice the stutter "head" replays.
            <strong> 0</strong> = classic full-slice repeats.{" "}
            <strong>5-15 ms</strong> = glitch buzz.{" "}
            <strong>20-50 ms</strong> = CD-skip.{" "}
            <strong>100+</strong> = phrase loop. In ♪ mode the skip
            length is BPM-locked — pick "1/32" for a tight glitch
            that always sits on the grid.
          </>
        }
      />
      <LabeledKnob
        label="reps max"
        value={stutterReps}
        onChange={(v) => setParam("stutter_max_reps", v)}
        min={0} max={16} step={1}
        defaultValue={0}
        formatValue={(v) => v.toFixed(0)}
        tooltip={
          <>
            Upper bound on the random repeat count per stutter event.
            Engine picks 2 to N. Higher = denser, machine-gun
            patterns. <strong>0</strong> disables stutter entirely.
          </>
        }
      />
      <LabeledKnob
        label="spread"
        value={stutterSpread}
        onChange={(v) => setParam("stutter_spread", v)}
        min={0} max={1} step={0.05}
        defaultValue={0}
        formatValue={(v) => v.toFixed(2)}
        tooltip={
          <>
            Skip-length variance per stutter.{" "}
            <strong>0</strong> = uniform.{" "}
            <strong>1.0</strong> = each stutter picks its own random
            head length — mixes glitch blips, medium skips, and
            phrase stutters organically.
          </>
        }
      />
      <LabeledKnob
        label="reverse"
        value={reverseChance}
        onChange={(v) => setParam("reverse_chance", v)}
        min={0} max={1} step={0.05}
        defaultValue={0}
        formatValue={(v) => v.toFixed(2)}
        tooltip={
          <>
            Probability that each slice plays backwards. Independent
            of stutter — a slice can be reversed AND stuttered.
            Stereo channels reverse together.
          </>
        }
      />
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// OUTPUT module — slurmify button + progress + output waveform.
// ──────────────────────────────────────────────────────────────────────
//
// Three states drive the body:
//
//   • idle — Slurmify button armed; no output yet.
//   • running — Progress bar + step description, button disabled.
//   • done — Output waveform visible above the (re-armed) button.
//
// Errors surface inline below the button.
// ──────────────────────────────────────────────────────────────────────

function OutputModule() {
  const isRunning = useSlurmStore((s) => s.isRunning)
  const progress  = useSlurmStore((s) => s.progress)
  const desc      = useSlurmStore((s) => s.desc)
  const error     = useSlurmStore((s) => s.error)
  const output    = useSlurmStore((s) => s.output)

  const status = isRunning
    ? "active"
    : error
      ? "error"
      : output
        ? "active"   // a green "ready" pulse looks right when an output exists
        : "idle"

  const badge = isRunning
    ? `${Math.round(progress * 100)}%`
    : output
      ? "ready"
      : error
        ? "error"
        : "armed"

  return (
    <RackModule color="output" name="output" status={status} badge={badge}>
      <OutputBody />
    </RackModule>
  )
}

function OutputBody() {
  const isRunning    = useSlurmStore((s) => s.isRunning)
  const progress     = useSlurmStore((s) => s.progress)
  const desc         = useSlurmStore((s) => s.desc)
  const error        = useSlurmStore((s) => s.error)
  const output       = useSlurmStore((s) => s.output)
  const outputFormat = useSlurmStore((s) => s.params.output_format)
  const seed         = useSlurmStore((s) => s.params.seed)
  const setParam     = useSlurmStore((s) => s.setParam)
  const burnedFileId = useFxStore((s) => s.burnedFileId)
  const backendUrl   = useBackendUrl()

  // ── FX chain binding ─────────────────────────────────────────────
  // Capture wavesurfer's underlying <audio> element and bind the FX
  // chain to it.  Idempotent — useFxChain skips re-binding when it
  // already has a chain (per ADR-0003).  We hold the element in
  // local state because the binding effect inside useFxChain needs
  // a stable reference, and useState gives us that.
  //
  // The chain also exposes an AnalyserNode tap (off the dry phaser
  // output, so what the meter shows matches what you hear).  We
  // forward it to the VuMeter further down.
  const [fxAudioEl, setFxAudioEl] = useState<HTMLMediaElement | null>(null)
  const { analyser, analyserBuf } = useFxChain(fxAudioEl)

  // ── Save-as state (transient) ────────────────────────────────────
  // Used for the "save…" button on the active output (dry slurm OR
  // burned-FX, whichever is currently loaded into the player).
  const [saveStatus, setSaveStatus] = useState<{
    kind: "saving" | "saved" | "error"
    message?: string
  } | null>(null)

  const handleSaveOutput = async () => {
    // Decide what file_id to download — burned takes priority over
    // dry slurm.  Same priority as the playing-URL resolution below.
    const fileId = burnedFileId ?? output?.output_id
    if (!fileId) return
    setSaveStatus({ kind: "saving" })
    const fmt = outputFormat
    const label = burnedFileId ? "Burned-FX" : "Slurm"
    const result = await saveBackendFileAs({
      fileId,
      defaultFilename: `siena_${label.toLowerCase()}.${fmt}`,
      dialogTitle:     `Save ${label} Output`,
      filters:         audioFilter(fmt),
    })
    if (result.kind === "saved") {
      setSaveStatus({ kind: "saved" })
      // Auto-clear the success indicator after a couple seconds — it's
      // a confirmation, not a permanent state.
      setTimeout(() => setSaveStatus(null), 2500)
    } else if (result.kind === "cancelled") {
      // User cancelled — silent (no toast, no error indicator).
      setSaveStatus(null)
    } else {
      setSaveStatus({ kind: "error", message: result.message })
    }
  }

  // Seed is stored as `number | null`; edited as a string for the
  // same reasons BPM is.  Empty = "fresh randomness each run".
  const [seedText, setSeedText] = useState<string>(seed === null ? "" : String(seed))
  useEffect(() => {
    setSeedText(seed === null ? "" : String(seed))
  }, [seed])
  const commitSeed = () => {
    const trimmed = seedText.trim()
    if (trimmed === "") {
      setParam("seed", null)
      return
    }
    const n = parseInt(trimmed, 10)
    if (Number.isFinite(n) && n >= 0) {
      setParam("seed", n)
      setSeedText(String(n))
    } else {
      setSeedText(seed === null ? "" : String(seed))
    }
  }

  const { run } = useSlurmifyJob()

  return (
    <div className="flex flex-col gap-2">
      {/* Format dropdown — picks the export format slurmcore writes to. */}
      <LabeledSelect
        label="format"
        value={outputFormat}
        onValueChange={(v) =>
          setParam(
            "output_format",
            v as "wav" | "mp3" | "flac" | "ogg" | "aiff" | "aac",
          )
        }
        options={[
          { value: "wav",  label: "WAV (16-bit PCM, lossless)" },
          { value: "flac", label: "FLAC (lossless compressed)" },
          { value: "mp3",  label: "MP3 (~190 kbps VBR)" },
          { value: "aac",  label: "AAC / m4a (192 kbps)" },
          { value: "ogg",  label: "OGG Vorbis (lossy)" },
          { value: "aiff", label: "AIFF (16-bit PCM)" },
        ]}
        triggerWidth="13rem"
        disabled={isRunning}
        tooltip={
          <>
            Container format for the slurm output file. WAV / FLAC /
            AIFF are lossless. MP3 / AAC / OGG are lossy and smaller.
            All preserve the source's channel count (mono in →
            mono out; stereo in → stereo out).
          </>
        }
        hint="output container — wav/flac/aiff are lossless"
      />

      {/* Seed — empty = fresh randomness; integer = reproducible runs */}
      <LabeledTextbox
        label="seed"
        value={seedText}
        onChange={setSeedText}
        onBlur={commitSeed}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur() }}
        type="number"
        min={0}
        step={1}
        placeholder="random"
        inputWidth="8rem"
        disabled={isRunning}
        tooltip={
          <>
            RNG seed for reproducible slurmify runs. Same seed + same
            params = bit-for-bit identical output. Affects: MAX RANDOM
            slice durations, slice shuffle order, reverse / stutter
            chance rolls, stutter length spread. Empty = fresh
            randomness on every run (default).
          </>
        }
      />

      {/* Action row — Slurmify button + status text */}
      <div className="flex items-center gap-3">
        <Tip
          text={
            isRunning
              ? "A slurmify job is in progress. Wait for it to finish or stop the backend to abort."
              : "Run the full slurmify pipeline: stretch → slice → per-slice DSP → concat → normalize. Output appears below when done."
          }
        >
          <Button
            size="lg"
            variant="default"
            disabled={isRunning}
            onClick={() => void run()}
            className="min-w-[140px]"
          >
            {isRunning ? (
              <>
                <Loader2 className="animate-spin" />
                slurmifying…
              </>
            ) : (
              <>
                <Sparkles />
                slurmify
              </>
            )}
          </Button>
        </Tip>

        {/* Inline progress label — what step are we on */}
        {isRunning && (
          <span className="text-[11px] tabular-nums text-slurm-muted">
            {desc || "starting…"}
          </span>
        )}

        {/* Error message — surfaces backend / SSE errors */}
        {error && !isRunning && (
          <span className="text-[11px] text-slurm-danger">{error}</span>
        )}
      </div>

      {/* Progress bar — only visible while running */}
      {isRunning && (
        <Progress value={Math.round(progress * 100)} />
      )}

      {/* Siena dancer — shown while slurmify is running.  Sized at
          v0.1.6's 200px default; the desc field doubles as a caption so
          the user gets visual + textual progress feedback. */}
      {isRunning && (
        <div className="flex justify-center py-2">
          <Dancer
            width={180}
            caption={desc || "starting…"}
          />
        </div>
      )}

      {/* Output waveform — once we have an output_id.  When the user
          has burned FX, we play the BURNED file URL instead of the
          dry slurm.  The FX chain still applies on top, so burning
          + twisting after-the-fact stacks.
          The VU meter sits to the right of the badge, fed by the
          analyser tap from useFxChain — gives the user immediate
          visual feedback that audio is flowing through the chain. */}
      {output && !isRunning && (() => {
        // Resolve the URL to actually play.  Burned file > dry slurm.
        const playingUrl = burnedFileId && backendUrl
          ? `${backendUrl}/files/${burnedFileId}`
          : output.url
        const playingId  = burnedFileId ?? output.output_id
        return (
          <div className="flex flex-col gap-1.5 mt-1">
            <div className="flex items-center gap-2 text-[11px] text-slurm-muted">
              <span className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider",
                burnedFileId
                  ? "bg-slurm-cyan/15 text-slurm-cyan"
                  : "bg-primary/15 text-primary",
              )}>
                {burnedFileId ? "burned" : "output"}
              </span>
              <span className="font-mono truncate max-w-[180px]">{playingId}</span>

              {/* Live VU meter — only renders once the FX chain has
                  bound the AnalyserNode.  Until then the segments
                  show "all dark" which is the natural pre-play
                  state anyway. */}
              <Tip text="Audio level (RMS) of what you're currently hearing — slurm output with the live FX chain applied. Top three segments turn rose when approaching clip; brighter all-cyan = healthy mix.">
                <span className="ml-2 cursor-help">
                  <VuMeter
                    analyser={analyser}
                    analyserBuf={analyserBuf}
                    segments={20}
                  />
                </span>
              </Tip>

              {/* Save-as — exports whatever's currently in the player
                  (dry slurm OR burned-FX), through Tauri's native
                  save dialog.  Silently no-ops on cancel. */}
              <Tip
                text={
                  burnedFileId
                    ? "Save the FX-burned audio to disk. The chosen path persists across app restarts (unlike the temp-file the player streams from)."
                    : "Save the dry slurm output to disk. The FX chain is NOT baked in — twist the FX knobs and click 'burn FX' first if you want the effects on disk."
                }
              >
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto h-7 px-2 text-[11px]"
                  onClick={() => void handleSaveOutput()}
                  disabled={saveStatus?.kind === "saving"}
                >
                  {saveStatus?.kind === "saving" ? (
                    <>
                      <Loader2 className="!h-3 !w-3 animate-spin" />
                      saving…
                    </>
                  ) : saveStatus?.kind === "saved" ? (
                    <>
                      <Save className="!h-3 !w-3" />
                      saved ✓
                    </>
                  ) : (
                    <>
                      <Download className="!h-3 !w-3" />
                      save…
                    </>
                  )}
                </Button>
              </Tip>
            </div>
            {saveStatus?.kind === "error" && (
              <div className="text-[10px] text-slurm-danger ml-1">
                save failed: {saveStatus.message}
              </div>
            )}
            <WaveformPlayer
              url={playingUrl}
              height={70}
              onMediaElement={setFxAudioEl}
            />
          </div>
        )
      })()}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// FX module body — distortion / ring mod / delay / phaser knobs +
// Burn FX action.  Live preview routes through useFxChain (bound to
// the OUTPUT module's WaveformPlayer audio element).
// ──────────────────────────────────────────────────────────────────────

function FxBody() {
  const fx          = useFxStore((s) => s.params)
  const setFxParam  = useFxStore((s) => s.setParam)
  const isBurning   = useFxStore((s) => s.isRunning)
  const burnDesc    = useFxStore((s) => s.desc)
  const burnError   = useFxStore((s) => s.error)
  const burnedId    = useFxStore((s) => s.burnedFileId)
  const burnProg    = useFxStore((s) => s.progress)
  const resetFx     = useFxStore((s) => s.resetParams)
  const clearBurn   = useFxStore((s) => s.clearBurn)
  const slurmOutput = useSlurmStore((s) => s.output)
  const sourceFile  = useSlurmStore((s) => s.sourceFile)

  const { run: burnRun } = useBurnFxJob()

  // Decide what burn-fx will operate on.  Used for the button's
  // tooltip + label so the user knows whether they'll burn FX into
  // the slurm output (common) or directly onto the raw source (rare,
  // pre-slurmify).
  const burnTarget = slurmOutput ? "slurm output" : (sourceFile ? "raw source" : null)

  return (
    <div className="flex flex-col gap-3">
      {/* Knob row — 4 sub-sections, gap-separated.  Each section's
          first knob has a faint section divider chip on the left
          ("DIST", "RING", etc.) so the four-stage chain reads as
          a left-to-right signal flow. */}
      <div className="flex flex-wrap items-start gap-x-1 gap-y-3 pt-1">
        <FxSectionLabel name="dist" />
        <LabeledKnob
          label="drive"
          value={fx.distDrive}
          onChange={(v) => setFxParam("distDrive", v)}
          min={0} max={1} step={0.01}
          defaultValue={0}
          formatValue={(v) => v.toFixed(2)}
          tooltip={
            <>
              Tanh-shaped saturation. <strong>0</strong> = bypass.{" "}
              <strong>0.3</strong> = warm color.{" "}
              <strong>0.7+</strong> = aggressive clipping. The curve
              is normalized so output peaks stay near ±1 — louder
              clip levels don't bleed into raw gain.
            </>
          }
        />

        <FxSectionLabel name="ring" />
        <LabeledKnob
          label="freq"
          value={fx.ringFreq}
          onChange={(v) => setFxParam("ringFreq", v)}
          min={20} max={2000} step={1}
          defaultValue={200}
          formatValue={(v) => v.toFixed(0)}
          unit="Hz"
          tooltip={
            <>
              Carrier oscillator frequency. <strong>20-100 Hz</strong>{" "}
              = sub tremolo flutter. <strong>100-500</strong> = classic
              metallic ring. <strong>500+</strong> = inharmonic crunch.
            </>
          }
        />
        <LabeledKnob
          label="depth"
          value={fx.ringDepth}
          onChange={(v) => setFxParam("ringDepth", v)}
          min={0} max={1} step={0.01}
          defaultValue={0}
          formatValue={(v) => v.toFixed(2)}
          tooltip={
            <>
              Ring-mod blend amount. <strong>0</strong> = bypass
              (gain stays at 1). <strong>1</strong> = full sine
              modulation of the gain envelope.
            </>
          }
        />

        <FxSectionLabel name="delay" />
        <LabeledKnob
          label="time"
          value={fx.delayTime}
          onChange={(v) => setFxParam("delayTime", v)}
          min={0} max={2} step={0.01}
          defaultValue={0.3}
          formatValue={(v) => (v * 1000).toFixed(0)}
          unit="ms"
          tooltip={
            <>
              Delay-line length, 0–2 seconds. Display is in ms for
              read-at-a-glance. Pair with feedback for slap-back
              echoes, dub trails, or self-oscillating drones.
            </>
          }
        />
        <LabeledKnob
          label="feedback"
          value={fx.delayFb}
          onChange={(v) => setFxParam("delayFb", v)}
          min={0} max={0.95} step={0.01}
          defaultValue={0.35}
          formatValue={(v) => v.toFixed(2)}
          tooltip={
            <>
              How much of the delayed signal feeds back into the
              line. <strong>0</strong> = single repeat.{" "}
              <strong>0.5</strong> = ~6 audible repeats.{" "}
              <strong>0.9+</strong> = drone / self-oscillation. Capped
              at 0.95 to prevent runaway clipping.
            </>
          }
        />
        <LabeledKnob
          label="mix"
          value={fx.delayMix}
          onChange={(v) => setFxParam("delayMix", v)}
          min={0} max={1} step={0.01}
          defaultValue={0}
          formatValue={(v) => v.toFixed(2)}
          tooltip={
            <>
              Wet/dry blend. <strong>0</strong> = bypass.{" "}
              <strong>0.5</strong> = equal dry + wet (classic).{" "}
              <strong>1</strong> = wet only (delay-only signal).
            </>
          }
        />

        <FxSectionLabel name="phaser" />
        <LabeledKnob
          label="rate"
          value={fx.phaseRate}
          onChange={(v) => setFxParam("phaseRate", v)}
          min={0.05} max={10} step={0.05}
          defaultValue={1.0}
          formatValue={(v) => v.toFixed(2)}
          unit="Hz"
          tooltip={
            <>
              LFO sweep rate. <strong>0.05-0.5 Hz</strong> = slow
              cosmic sweep. <strong>1-3</strong> = classic phaser
              swirl. <strong>5+</strong> = throbbing modulation.
            </>
          }
        />
        <LabeledKnob
          label="depth"
          value={fx.phaseDepth}
          onChange={(v) => setFxParam("phaseDepth", v)}
          min={0} max={1} step={0.01}
          defaultValue={0}
          formatValue={(v) => v.toFixed(2)}
          tooltip={
            <>
              Phaser intensity — controls both the LFO sweep range
              AND the wet/dry mix in lockstep. <strong>0</strong> =
              bypass. <strong>1</strong> = full sweep + balanced
              wet/dry.
            </>
          }
        />
      </div>

      {/* Action row — Burn FX + reset */}
      <div className="flex items-center gap-3">
        <Tip
          text={
            isBurning
              ? "A burn-FX job is already running. Wait for it to finish."
              : burnTarget
                ? <>
                    Bake the current FX settings into a NEW audio file
                    derived from the {burnTarget}. The OUTPUT player
                    will switch to playing that burned file. The live
                    Web Audio FX still applies on top, so you can keep
                    twisting knobs to layer effects.
                  </>
                : "Drop a file or run slurmify first — burn-FX needs an audio source."
          }
        >
          <Button
            size="default"
            variant="default"
            disabled={isBurning || !burnTarget}
            onClick={() => void burnRun()}
            className="min-w-[120px]"
          >
            {isBurning ? (
              <>
                <Loader2 className="animate-spin" />
                burning…
              </>
            ) : (
              <>
                <Flame />
                burn FX
              </>
            )}
          </Button>
        </Tip>

        {isBurning && (
          <span className="text-[11px] tabular-nums text-slurm-muted">
            {burnDesc || "starting…"}
          </span>
        )}

        {burnError && !isBurning && (
          <span className="text-[11px] text-slurm-danger">{burnError}</span>
        )}

        {/* Revert to dry slurm — only when something is currently
            burned in (the OUTPUT player would be using the burned URL). */}
        {burnedId && !isBurning && (
          <Tip text="Drop the burned-FX file and play the dry slurm output again. The FX knob settings stay; only the bake is reverted.">
            <Button
              size="sm"
              variant="ghost"
              className="text-slurm-muted hover:text-slurm-fg"
              onClick={clearBurn}
            >
              revert to dry
            </Button>
          </Tip>
        )}

        {/* Reset all FX knobs to defaults — purely UI, doesn't touch
            any burned file. */}
        <Tip text="Set all 8 FX knobs back to their defaults (drive 0, depth 0, mix 0, etc.). Live preview becomes effectively bypassed. Doesn't affect any already-burned file.">
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto text-slurm-muted hover:text-slurm-fg"
            onClick={resetFx}
          >
            <RotateCcw className="!h-3 !w-3" />
            reset
          </Button>
        </Tip>
      </div>

      {/* Progress bar — only visible while burning */}
      {isBurning && (
        <Progress value={Math.round(burnProg * 100)} />
      )}

      {/* Siena dancer — smaller for the FX module (the rack row is
          already dense with 8 knobs).  Caption echoes the burn step
          so the dancer doubles as a tasteful progress label. */}
      {isBurning && (
        <div className="flex justify-center py-1">
          <Dancer width={120} caption={burnDesc || "starting…"} />
        </div>
      )}
    </div>
  )
}

/** Section divider chip used to break up the FX knob row visually
 *  into its four logical stages.  Renders as a thin vertical strip
 *  with a small uppercase label inside the rack module body. */
function FxSectionLabel({ name }: { name: string }) {
  return (
    <div
      className={cn(
        "flex h-[120px] flex-col items-center justify-center",
        "px-1 mr-1 select-none",
        "text-[9px] uppercase tracking-[0.15em] text-slurm-muted",
        "border-l border-slurm-border-2",
      )}
    >
      <span style={{ writingMode: "vertical-rl" }}>{name}</span>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// VIDEO module body — YouTube-ready MP4 export.
//
// Renders the slurm output (or burned-FX output) over the pre-encoded
// loop animation (assets/siebaSlurm_A003.mp4) at 1920×1080.  The
// backend stream-copies the video and AAC-encodes the audio so the
// render is fast (a few seconds for typical clip lengths).
//
// User-visible flow:
//   1. Type a title + creator name (both optional; backend defaults to
//      "Subvoyant Slurm <jumble>" / "Subvoyant SIENA Slurmer").
//   2. Optionally toggle "include source filename" — embeds the
//      original input filename into the PATCH JSON metadata atom.
//   3. Click "render YouTube MP4".  Progress streams via SSE.
//   4. On done, a <video> preview appears + a "save…" button that
//      hands the file off through Tauri's native save dialog.
// ──────────────────────────────────────────────────────────────────────

function VideoBody() {
  const meta            = useVideoStore((s) => s.metadata)
  const setMetadata     = useVideoStore((s) => s.setMetadata)
  const isRendering     = useVideoStore((s) => s.isRunning)
  const renderProgress  = useVideoStore((s) => s.progress)
  const renderDesc      = useVideoStore((s) => s.desc)
  const renderError     = useVideoStore((s) => s.error)
  const renderedFileId  = useVideoStore((s) => s.renderedFileId)
  const clearRender     = useVideoStore((s) => s.clearRender)

  const slurmOutput     = useSlurmStore((s) => s.output)
  const sourceFile      = useSlurmStore((s) => s.sourceFile)
  const burnedFileId    = useFxStore((s) => s.burnedFileId)
  const backendUrl      = useBackendUrl()

  const { run: renderRun } = useRenderVideoJob()

  const [saveStatus, setSaveStatus] = useState<{
    kind: "saving" | "saved" | "error"
    message?: string
  } | null>(null)

  // Tell the user what audio source the next render will use, so they
  // don't get a surprise "raw upload" video when they expected the
  // slurm output.
  const renderSourceLabel = burnedFileId
    ? "FX-burned output"
    : slurmOutput
      ? "slurm output"
      : sourceFile
        ? "raw source (no slurm yet)"
        : null

  const handleSaveVideo = async () => {
    if (!renderedFileId) return
    setSaveStatus({ kind: "saving" })
    // Build a default filename matching the v0.1.6 convention
    // ("Subvoyant_Siena_Slurmify_<title>_<jumble>.mp4") at least at
    // the prefix — the actual jumble is generated server-side.  We
    // use the title field if set, falling back to the file_id.
    const safeTitle = (meta.title || "slurm")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 32)
    const defaultFilename = `Subvoyant_Siena_Slurmify_${safeTitle}.mp4`
    const result = await saveBackendFileAs({
      fileId:          renderedFileId,
      defaultFilename,
      dialogTitle:     "Save Video Export",
      filters:         mp4Filter(),
    })
    if (result.kind === "saved") {
      setSaveStatus({ kind: "saved" })
      setTimeout(() => setSaveStatus(null), 2500)
    } else if (result.kind === "cancelled") {
      setSaveStatus(null)
    } else {
      setSaveStatus({ kind: "error", message: result.message })
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Title — used in the MP4 metadata + safe-title filename slug */}
      <LabeledTextbox
        label="title"
        value={meta.title}
        onChange={(v) => setMetadata("title", v)}
        type="text"
        placeholder="my slurm"
        inputWidth="20rem"
        disabled={isRendering}
        tooltip={
          <>
            Free-form video title. Embedded into the MP4 metadata atom
            (visible in YouTube "Show More" + most media players) and
            used to build the safe-title slug in the filename.
            Max 40 characters of [a-z0-9_] survive the slug pass.
            Leave blank → backend generates "Subvoyant Slurm
            &lt;jumble&gt;" automatically.
          </>
        }
      />

      {/* Creator — embedded as MP4 "artist" atom */}
      <LabeledTextbox
        label="creator"
        value={meta.creator}
        onChange={(v) => setMetadata("creator", v)}
        type="text"
        placeholder="Subvoyant SIENA Slurmer"
        inputWidth="20rem"
        disabled={isRendering}
        tooltip={
          <>
            Artist name shown in YouTube + media-player UIs. Embedded
            into the MP4's <code>artist</code> metadata atom. Leave
            blank → defaults to "Subvoyant SIENA Slurmer".
          </>
        }
      />

      {/* Include-source toggle — affects PATCH JSON only */}
      <LabeledSwitch
        label="include source"
        checked={meta.includeSourceFilename}
        onCheckedChange={(v) => setMetadata("includeSourceFilename", v)}
        disabled={isRendering}
        tooltip={
          <>
            Embed the ORIGINAL INPUT FILENAME inside the MP4's
            self-describing PATCH JSON blob (ADR-0008). Useful for
            reproducibility — a future "import patch" feature could
            pair the params with their source. Off by default because
            some users prefer not to leak source-file names in
            uploads.
          </>
        }
      />

      {/* Action row — Render button + status */}
      <div className="flex items-center gap-3 mt-1">
        <Tip
          text={
            isRendering
              ? "A render is in progress. Wait for it to finish before queueing another."
              : renderSourceLabel
                ? <>Render a 1920×1080 MP4 with the looping slurmify animation + your <strong>{renderSourceLabel}</strong> as the audio track. Stream-copied video + AAC audio = renders in seconds.</>
                : "Drop a file first — render-video needs an audio source."
          }
        >
          <Button
            size="default"
            variant="default"
            disabled={isRendering || !renderSourceLabel}
            onClick={() => void renderRun()}
            className="min-w-[160px]"
          >
            {isRendering ? (
              <>
                <Loader2 className="animate-spin" />
                rendering…
              </>
            ) : (
              <>
                <Film />
                render YouTube MP4
              </>
            )}
          </Button>
        </Tip>

        {!isRendering && renderSourceLabel && (
          <span className="text-[10px] text-slurm-muted italic">
            audio source: {renderSourceLabel}
          </span>
        )}

        {isRendering && (
          <span className="text-[11px] tabular-nums text-slurm-muted">
            {renderDesc || "starting…"}
          </span>
        )}

        {renderError && !isRendering && (
          <span className="text-[11px] text-slurm-danger">{renderError}</span>
        )}
      </div>

      {/* Progress bar — only visible while rendering */}
      {isRendering && (
        <Progress value={Math.round(renderProgress * 100)} />
      )}

      {/* Siena dancer — render-video runs ffmpeg + AAC encode in the
          background; the dancer reassures the user that something is
          happening even when the SSE desc is generic ("ffmpeg…"). */}
      {isRendering && (
        <div className="flex justify-center py-1">
          <Dancer width={140} caption={renderDesc || "starting…"} />
        </div>
      )}

      {/* Video preview — once we have a renderedFileId.
          The <video> element streams from the backend with HTTP
          range support, so seek-without-refetch works.  Width
          capped to keep the preview proportional inside the rack. */}
      {renderedFileId && backendUrl && !isRendering && (
        <div className="flex flex-col gap-1.5 mt-1">
          <div className="flex items-center gap-2 text-[11px] text-slurm-muted">
            <span className="rounded bg-slurm-rose/15 px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider text-slurm-rose">
              rendered
            </span>
            <span className="font-mono truncate max-w-[180px]">
              {renderedFileId}
            </span>
            <Tip text="Drop the rendered preview without saving — useful when you want to re-render with different metadata without keeping the previous attempt around.">
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[10px] text-slurm-muted hover:text-slurm-fg"
                onClick={clearRender}
              >
                discard
              </Button>
            </Tip>
            <Tip text="Save the rendered MP4 to a folder of your choice. The chosen path persists across app restarts (unlike the temp file the preview streams from).">
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto h-7 px-2 text-[11px]"
                onClick={() => void handleSaveVideo()}
                disabled={saveStatus?.kind === "saving"}
              >
                {saveStatus?.kind === "saving" ? (
                  <>
                    <Loader2 className="!h-3 !w-3 animate-spin" />
                    saving…
                  </>
                ) : saveStatus?.kind === "saved" ? (
                  <>
                    <Save className="!h-3 !w-3" />
                    saved ✓
                  </>
                ) : (
                  <>
                    <Download className="!h-3 !w-3" />
                    save MP4…
                  </>
                )}
              </Button>
            </Tip>
          </div>
          {saveStatus?.kind === "error" && (
            <div className="text-[10px] text-slurm-danger ml-1">
              save failed: {saveStatus.message}
            </div>
          )}
          <video
            controls
            className={cn(
              "w-full max-w-[640px] rounded border border-slurm-border-2",
              "bg-black",
            )}
            src={`${backendUrl}/files/${renderedFileId}`}
          />
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// ConnectionIndicator (unchanged from C2)
// ──────────────────────────────────────────────────────────────────────

function ConnectionIndicator({ status }: { status: BackendStatus }) {
  let dotVar: string
  let label:  string
  let pulsing: boolean = false
  let tipText: React.ReactNode

  switch (status.kind) {
    case "checking":
      dotVar  = "var(--slurm-warn)"
      label   = "looking for backend…"
      pulsing = true
      tipText = "Polling for the Python backend. Make sure you've started it: source .venv/bin/activate && python src-python/server.py"
      break
    case "ready":
      dotVar = "var(--slurm-ok)"
      label  = `port ${status.port}`
      tipText = (
        <>
          Backend connected on <strong>localhost:{status.port}</strong>{" "}
          (v{status.version}). All API calls — upload, slurmify,
          burn-fx, file serving — go through this port.
        </>
      )
      break
    case "error":
      dotVar = "var(--slurm-danger)"
      label  = "backend offline"
      tipText = status.message
      break
  }

  return (
    <Tip text={tipText}>
      <div
        className={cn(
          "flex items-center gap-2",
          "rounded-full border border-slurm-border bg-slurm-bg",
          "px-2.5 py-1 text-[11px] text-slurm-fg",
          "cursor-help",
        )}
      >
        <span
          className={cn(
            "inline-block h-2 w-2 shrink-0 rounded-full",
            pulsing && "animate-pulse-glow",
          )}
          style={{
            backgroundColor: dotVar,
            boxShadow: pulsing ? undefined : `0 0 4px ${dotVar}`,
          }}
        />
        <span className="font-mono tabular-nums">{label}</span>
        {status.kind === "error" && (
          <Tip text="Re-resolve the backend URL and reload the app. Click this if the backend was restarted on a different port.">
            <Button
              size="sm"
              variant="ghost"
              className="h-5 w-5 p-0"
              onClick={() => {
                invalidateBackendUrl()
                window.location.reload()
              }}
            >
              <RotateCw className="!h-3 !w-3" />
            </Button>
          </Tip>
        )}
      </div>
    </Tip>
  )
}
