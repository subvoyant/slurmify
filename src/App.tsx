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
import { Dices, Download, Film, Flame, Loader2, RotateCcw, RotateCw, Save, Sparkles } from "lucide-react"
import { cn } from "./lib/utils"
import { useBackend, type BackendStatus } from "./hooks/useBackend"
import { useSkinStore } from "./stores/skinStore"
import { useSlurmStore, type AnalysisResult } from "./stores/slurmStore"
import { useFxStore, type DistShape, type SweepWave } from "./stores/fxStore"
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
import { open as openInShell } from "@tauri-apps/plugin-shell"

// ── Brand mark — Siena (the cat) ──────────────────────────────────────
// Siena is the late-20s Siamese cat that the Subvoyant apps are named
// after.  Her portrait lives in graphic/icon/subvoyant.iconset/ as
// the macOS .iconset folder for the app bundle (16-512 px).  We
// import the 128×128 PNG here — at 28 px display × 2x Retina = 56 px
// rendered, the 128 source gives us crisp downscaling without bloating
// the bundle.  The animated dancer GIF still plays during slurmify
// processing (in the OUTPUT module); for the brand mark a still
// portrait is the right read.
import sienaIcon from "../graphic/icon/subvoyant.iconset/icon_128x128.png"

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
import { noteToMs, type NoteLabel } from "./lib/note-mode"
import { ResolutionPicker, type Resolution } from "./components/ResolutionPicker"
import { BeatMaskStrip } from "./components/BeatMaskStrip"
import { InOutTrimRow } from "./components/InOutTrimRow"
import { TopBar } from "./components/TopBar"
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
        <div className="flex items-center gap-3">
          {/* Siena icon + SIENA SLURMER wordmark, both wrapped in a
              single clickable button that opens subvoyant.com in the
              user's default browser via Tauri's plugin-shell.  We
              avoid <a target="_blank"> because Tauri 2's webview can
              either block or in-window-open external links depending
              on platform; plugin-shell.open() forces the OS default
              browser which is what we want.  Both the icon and the
              title text are inside the same button so either can be
              clicked — matches what you'd expect from any branded
              app's top-left corner. */}
          <button
            type="button"
            aria-label="Visit subvoyant.com"
            title="Visit subvoyant.com"
            onClick={() => {
              void openInShell("https://www.subvoyant.com").catch((e) => {
                // eslint-disable-next-line no-console
                console.warn("[slurm] failed to open subvoyant.com:", e)
              })
            }}
            className={cn(
              "group flex items-center gap-3",
              "rounded px-1 py-0.5 -mx-1 -my-0.5",
              "transition-all hover:bg-white/5",
              "focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              "cursor-pointer",
            )}
          >
            <img
              src={sienaIcon}
              alt="Siena"
              draggable={false}
              className={cn(
                "h-7 w-auto shrink-0 rounded-sm",
                "transition-all",
                // Slight glow on hover so the icon feels alive and
                // the link affordance reads.
                "group-hover:drop-shadow-[0_0_6px_var(--slurm-cyan)]",
              )}
            />

            {/* Wordmark — Major Mono Display silk-screened onto the
                aluminum top-rail.  Tracked-out wide so the caps-only
                geometric shapes read like an actual product badge.
                Inset+drop shadow combo simulates etched ink.
                Hover-brightening is handled by the icon's drop-shadow
                glow rather than animating this text-shadow — a
                Tailwind arbitrary class with multi-stop rgba() commas
                is brittle (the JIT splits on commas). */}
            <h1
              className={cn(
                "font-display text-lg tracking-[0.25em] text-slurm-cyan",
                "leading-none",
              )}
              style={{
                textShadow:
                  "0 1px 0 rgba(0,0,0,0.65), 0 -1px 0 rgba(255,255,255,0.06), 0 0 14px color-mix(in oklab, var(--slurm-cyan) 35%, transparent)",
              }}
            >
              SIENA SLURMER
            </h1>
          </button>

          {/* Version readout — sits OUTSIDE the link button so
              clicking the version doesn't open subvoyant.com (a
              version number isn't a navigational target). */}
          <span className="lcd text-[14px] tracking-wide text-slurm-muted">
            v0.2.1
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ConnectionIndicator status={status} />
          <SkinPicker />
        </div>
      </header>

      {/* ── Sticky TopBar (preset manager + utility actions) ──────── */}
      {/* Hosted OUTSIDE <main> so its sticky positioning measures
          against the body's scroll, not against <main>'s padding.
          The bar's own px-3 py-1.5 supplies its internal spacing —
          no need for the parent to pad around it.  Renders for both
          source-loaded and empty states; randomize is internally
          disabled when no file is loaded (UtilityBar handles it).
          See src/components/TopBar.tsx for the full layout rationale
          and the W5b history (merging two separate rows into one
          sticky bar). */}
      <TopBar />

      {/* ── Main rack ─────────────────────────────────────────────── */}
      <main className="flex flex-1 flex-col gap-2 p-3">
        {/* INPUT module */}
        <RackModule
          color="input"
          name="input"
          status={hasSource ? "active" : "idle"}
          badge={hasSource ? "loaded" : "empty"}
        >
          <SourceModuleBody />
        </RackModule>

        {/* SLICING + STUTTER — side-by-side row.  SLICING is the
            information-dense centerpiece (resolution chips, knob
            trio, BPM override, beat-mask chip grid) and historically
            ran full-width with empty horizontal space to the right
            of the chip strip.  STUTTER's five small knobs slot
            naturally into that empty real estate when stacked into
            two columns, tightening the rack vertically.
            Layout: SLICING flexes to fill remaining width, STUTTER
            holds a fixed 320 px column on the right.  Below the lg
            breakpoint the grid collapses to a single column and the
            two modules stack vertically again — SLICING needs the
            horizontal room for the resolution chip row at narrower
            widths. */}
        {hasSource && (
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_500px]">
            <RackModule color="slicing" name="slicing" status="idle">
              <SlicingBody />
            </RackModule>
            <RackModule color="stutter" name="stutter" status="idle">
              <StutterBody />
            </RackModule>
          </div>
        )}

        {/* STRETCH + BEAT TRIM — side-by-side row.  These two modules
            are both small (3 controls each) so they read as a
            natural pair when placed in a 2-column grid: STRETCH
            shapes the timing/pitch up front, BEAT TRIM tightens the
            individual slices.  On narrower windows the grid wraps
            via grid-cols-1 to keep things readable. */}
        {hasSource && (
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            <RackModule color="stretch" name="stretch" status="idle">
              <StretchBody />
            </RackModule>
            <RackModule color="trim" name="beat trim" status="idle">
              <BeatTrimBody />
            </RackModule>
          </div>
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
          v0.2.1 — signed + notarized DMG, FX-on-by-default for YouTube renders, sticky TopBar, asset bundling fixes.{" "}
          <span className="text-slurm-rose">
            Next: tester feedback round, then v0.3 feature work.
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

      {/* Two-column layout below the resolution picker.
          LEFT column: knob trio (transient / envelope / shuffle) on
            top row, BPM-override textbox on bottom row.
          RIGHT column: beat mask chip strip, sitting next to the
            knobs at the parent flex's natural `gap-6` distance so
            it reads as part of the same control unit (not banished
            to the panel's right edge — `ml-auto` made the strip and
            the knob group feel like two unrelated tools).
          Why a two-column layout?  At 1/32 the chip strip is 4 rows
          of 8 chips; the left column is already two rows tall (knobs
          + textbox stacked).  Side-by-side, neither column pushes
          the SLICING panel taller than the chip strip itself —
          previously the chip strip and the BPM textbox were stacked
          vertically and at 1/32 the panel grew uncomfortably tall
          and the strip "intersected" the BPM area visually.
          `items-start` keeps both columns top-aligned so the chip
          strip's first row lines up with the knob row's tops. */}
      <div className="flex flex-wrap items-start gap-6 pt-1">
        {/* LEFT column — knob trio over BPM override, stacked
            vertically with a small gap.  shrink-0 prevents the
            beat-mask grid (which lives to the right) from squeezing
            the BPM textbox label. */}
        <div className="flex flex-col gap-2 shrink-0">
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
        {/* RIGHT column — beat mask chip strip.  Sits at the parent
            flex's natural `gap-6` (24 px) from the LEFT column, so
            it visually belongs to the same control group instead of
            being pushed to the panel's right edge.  flex-wrap on the
            parent will let the strip drop below the LEFT column on
            narrow viewports rather than overflowing the panel. */}
        <BeatMaskStrip
          resolution={resolution}
          mask={beatMask}
          onChange={(m) => setParam("beat_mask", m)}
        />
      </div>
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
      {/* "Preserve pitch" toggle sits between speed and pitch — the
          stretch operation it modifies happens at speed, and the
          consequence (pitch stays the same) belongs visually next
          to the pitch knob.  Two-word label wraps onto two lines
          inside the 76px cell; .panel-label uppercases it to
          "PRESERVE PITCH". */}
      <KnobToggle
        label="Preserve pitch"
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
      <LabeledKnob
        label="Pitch offset"
        value={pitchShift}
        onChange={(v) => setParam("pitch_shift_semitones", v)}
        min={-24} max={24} step={1}
        defaultValue={0}
        formatValue={(v) => (v > 0 ? `+${v}` : String(v))}
        unit="st"
        tooltip={
          <>
            Pitch offset in semitones, applied AFTER the speed change.
            ±12 = one octave. ±24 = two. Works best with "Preserve
            pitch" ON so speed and pitch stay decoupled.
            Double-click resets to 0.
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

  // Three KnobNoteToggle cells with toggleLayout="right" — the ms/♪
  // toggle and BPM hint live in a column to the RIGHT of the knob
  // instead of stacked below it.  Each cell is ~140 px wide × ~80
  // px tall (matching a bare LabeledKnob's height) so BEAT TRIM
  // doesn't outgrow STRETCH vertically when the two share a row.
  // gap-6 (24 px) between cells gives the wider cells room to
  // breathe and reads as a deliberate horizontal layout, not a
  // packed strip.
  return (
    <div className="flex flex-wrap gap-6 pt-1">
      <KnobNoteToggle
        label="trim start"
        msValue={trimStart}
        onMsChange={(v) => setParam("beat_trim_start_ms", v)}
        msMin={0} msMax={500} msStep={5}
        msDefault={0}
        noteValue={trimStartNote}
        onNoteChange={(v: NoteLabel) => setParam("beat_trim_start_note", v)}
        mode={trimStartMode}
        onModeChange={(m) => setParam("beat_trim_start_mode", m as "ms" | "♪")}
        toggleLayout="right"
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
        onModeChange={(m) => setParam("beat_trim_end_mode", m as "ms" | "♪")}
        toggleLayout="right"
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
        onModeChange={(m) => setParam("beat_gap_mode", m as "ms" | "♪")}
        toggleLayout="right"
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

  // Olympic-rings layout — STUTTER lives in a 500 px column beside
  // SLICING.  A 6-column × 2-row grid splits the rack width into 6
  // equal slots; each knob spans 2 slots (centered in its span), and
  // the bottom row's slots are shifted by 1 so the bottom knobs sit
  // BETWEEN the top three.  Visual map:
  //
  //  cols  1  2  3  4  5  6
  //  row1 [chance] [reps  ] [revers]   ← top three at slots 1-2 / 3-4 / 5-6
  //  row2    [skip ] [spread]          ← bottom two at slots 2-3 / 4-5
  //
  //   ●   ●   ●     ← centers at 1/6, 3/6, 5/6 of rack width
  //     ●   ●       ← centers at 2/6, 4/6 — the midpoints between top centers
  //
  // Vertical compression — the row-2 cells use `-mt-8` (-32 px) to
  // pull the bottom row up into the negative space below the top
  // knobs' value text.  Combined with `gap-y-0` on the grid, this
  // overlaps the bottom knobs' tops with the bottom of the top
  // knobs' label/value text — the Olympic-rings stagger, not just
  // a 2-row grid.  The bottom-row cells live in the same column
  // tracks as the top row but their CONTENT is offset upward, so
  // there's no horizontal collision (the top-row cells are at slots
  // 1-2 / 3-4 / 5-6 and bottom-row at 2-3 / 4-5, no overlap).
  // place-items-center horizontally centers each knob inside its
  // 2-col span so a 76 px knob and a 96 px knob both anchor at
  // their slot's midpoint.
  return (
    <div className="grid grid-cols-6 grid-rows-2 gap-y-0 pt-1 place-items-center">
      {/* TOP ROW — chance / reps max / reverse at slots 1-2 / 3-4 / 5-6.
          DOM order matches reading order (left → right) so the tab
          sequence is natural even though grid placement is explicit. */}
      <div className="row-start-1 col-start-1 col-span-2 flex justify-center">
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
      </div>
      <div className="row-start-1 col-start-3 col-span-2 flex justify-center">
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
      </div>
      <div className="row-start-1 col-start-5 col-span-2 flex justify-center">
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

      {/* BOTTOM ROW — skip / spread at slots 2-3 / 4-5, sitting in
          the column gaps between the top three for an Olympic-rings
          stagger.  -mt-8 (-32 px) pulls these cells UP into the
          negative space below the top row's value text so the bottom
          knobs visually overlap the top knobs' labels/values, like
          the bottom row of an Olympic-rings logo nesting into the
          gaps of the top row.  Skip is taller (KnobNoteToggle's mode
          toggle + hint) — the row track auto-grows to fit; spread
          top-aligns via its outer flex cell. */}
      <div className="row-start-2 col-start-2 col-span-2 flex justify-center -mt-8">
        <KnobNoteToggle
          label="skip"
          msValue={stutterSkip}
          onMsChange={(v) => setParam("stutter_skip_ms", v)}
          msMin={0} msMax={500} msStep={5}
          msDefault={0}
          noteValue={stutterSkipNote}
          onNoteChange={(v: NoteLabel) => setParam("stutter_skip_note", v)}
          mode={stutterSkipMode}
          onModeChange={(m) => setParam("stutter_skip_mode", m as "ms" | "♪")}
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
      </div>
      <div className="row-start-2 col-start-4 col-span-2 flex justify-center -mt-8">
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
      </div>
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
  // same reasons BPM is.  Empty = "auto-pick on next slurm" — the
  // useSlurmifyJob hook pre-rolls and persists the chosen value, so
  // after a run the field always shows the seed that was used and
  // the user can copy it for reproducible re-runs.
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
  // Dice button — rolls a fresh random seed and writes it both into
  // params (so the slurm uses it) and into the visible textbox.
  // Same 0..999_999 range as the auto-pre-roll in useSlurmifyJob, so
  // a manual roll and an auto roll are interchangeable.
  const rollSeed = () => {
    const n = Math.floor(Math.random() * 1_000_000)
    setParam("seed", n)
    setSeedText(String(n))
  }

  const { run } = useSlurmifyJob()

  return (
    <div className="flex flex-col gap-2">
      {/* Top action bar — format dropdown + seed textbox on the LEFT,
          slurmify button + status on the RIGHT.  All three controls
          (and the inline status) live on a single horizontal line so
          OUTPUT collapses from a 3-row stack to a single header
          row + the waveform below.  Format's "output container —
          wav/flac/aiff are lossless" hint is dropped to keep the row
          at one consistent height; the option labels themselves
          ("WAV (16-bit PCM, lossless)" etc.) already convey the same
          information.  flex-wrap lets the button drop to the next
          line on very narrow viewports rather than overflow. */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
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
          compactLabel
          tooltip={
            <>
              Container format for the slurm output file. WAV / FLAC /
              AIFF are lossless. MP3 / AAC / OGG are lossy and smaller.
              All preserve the source's channel count (mono in →
              mono out; stereo in → stereo out).
            </>
          }
        />

        {/* Seed — pre-rolled by useSlurmifyJob if blank, so after a
            run the field shows the actual seed used.  Dice button
            rerolls on demand — same range (0..999_999) as the
            auto-pre-roll, so manual and auto rolls are interchangeable. */}
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
          inputWidth="7rem"
          disabled={isRunning}
          compactLabel
          extras={
            <Tip text="Roll a fresh random seed.  The new value is written into the field immediately so you can see it before slurmifying.  Same 0..999_999 range as the auto-pick that runs when you slurmify with the seed left blank.">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 shrink-0"
                onClick={rollSeed}
                disabled={isRunning}
                aria-label="roll random seed"
              >
                <Dices className="h-4 w-4" />
              </Button>
            </Tip>
          }
          tooltip={
            <>
              RNG seed for reproducible slurmify runs. Same seed + same
              params = bit-for-bit identical output. Affects: MAX RANDOM
              slice durations, slice shuffle order, reverse / stutter
              chance rolls, stutter length spread.{" "}
              <strong>Empty</strong> = a fresh seed is rolled on the
              next slurmify and written here so you can see + copy it.
              Click the dice to roll one manually right now.
            </>
          }
        />

        {/* Slurmify button + status — pushed to the right via
            ml-auto so it always sits flush with the panel's right
            edge regardless of how wide format/seed render. */}
        <div className="ml-auto flex items-center gap-3">
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

  // Decide what burn-fx will operate on.
  const burnTarget = slurmOutput ? "slurm output" : (sourceFile ? "raw source" : null)

  // When the master bypass is on, every effect section dims
  // visually so the user can see at a glance that the chain is
  // currently passing through unchanged.
  const masterBypassed = fx.bypass

  return (
    <div className="flex flex-col gap-0 -mx-3 -mt-3">

      {/* ── TOP-RAIL: Roland-style yellow pinstripe + master bypass +
          "SLURM·FX" model plate.  Sits flush against the bottom edge
          of the rack header (negative margins on the parent push it
          right up against the seam, so the rail reads as part of
          the chassis rather than floating in the body padding). */}
      <FxTopRail
        bypass={fx.bypass}
        onToggleBypass={() => setFxParam("bypass", !fx.bypass)}
      />

      {/* ── MOD PANEL: olive zone for modulation effects ──────────── */}
      <div className={cn(
        "fx-panel-mod px-3 py-2 transition-opacity",
        masterBypassed && "opacity-50",
      )}>
        <FxPanelTitle name="modulation" />
        <div className="flex items-stretch gap-1 flex-wrap">

          {/* DIST */}
          <FxSubSection
            name="dist"
            enabled={fx.distEnabled}
            onToggle={() => setFxParam("distEnabled", !fx.distEnabled)}
            weight={4}
          >
            <LabeledKnob
              label="gain"
              value={fx.distGain}
              onChange={(v) => setFxParam("distGain", v)}
              min={-24} max={24} step={0.5}
              defaultValue={0}
              formatValue={(v) => v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1)}
              unit="dB"
              showDefaultMark
              disabled={!fx.distEnabled || masterBypassed}
              tooltip={<>Pre-distortion input gain (-24 to +24 dB).  Adds drive UPSTREAM of the shaper, so even soft shapes can clip aggressively at high gain.  Double-click resets to 0; the tick mark indicates unity.</>}
            />
            <LabeledKnob
              label="drive"
              value={fx.distDrive}
              onChange={(v) => setFxParam("distDrive", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.distEnabled || masterBypassed}
              tooltip={<>Saturation amount.  <strong>0</strong> = passthrough.  <strong>0.3</strong> = warm.  <strong>0.7+</strong> = aggressive.  Curve type set by the SHAPE selector.</>}
            />
            <FxShapeSelector
              value={fx.distShape}
              onChange={(v) => setFxParam("distShape", v)}
              disabled={!fx.distEnabled || masterBypassed}
            />
            <LabeledKnob
              label="tone"
              value={fx.distTone}
              onChange={(v) => setFxParam("distTone", v)}
              min={-1} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v > 0 ? `+${v.toFixed(2)}` : v.toFixed(2)}
              showDefaultMark
              disabled={!fx.distEnabled || masterBypassed}
              tooltip={<>Post-distortion tone tilt — high-shelf at 2 kHz.  <strong>-1</strong> dark (-12 dB).  <strong>+1</strong> bright (+12 dB).  Tick at 0 = flat.</>}
            />
          </FxSubSection>

          <FxRule />

          {/* RING — now with the new frequency-sweep LFO controls */}
          <FxSubSection
            name="ring"
            enabled={fx.ringEnabled}
            onToggle={() => setFxParam("ringEnabled", !fx.ringEnabled)}
            weight={6}
          >
            <LabeledKnob
              label="freq"
              value={fx.ringFreq}
              onChange={(v) => setFxParam("ringFreq", v)}
              min={20} max={2000} step={1}
              defaultValue={200}
              formatValue={(v) => v.toFixed(0)}
              unit="Hz"
              disabled={!fx.ringEnabled || masterBypassed || fx.ringSweepRate > 0}
              tooltip={<>
                Static carrier frequency.  Used when SWEEP RATE = 0.
                When the sweep is active, this knob is overridden —
                the carrier oscillates between LOW and HIGH cutoffs
                instead.
              </>}
            />
            <LabeledKnob
              label="depth"
              value={fx.ringDepth}
              onChange={(v) => setFxParam("ringDepth", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.ringEnabled || masterBypassed}
              tooltip={<>Ring-mod blend amount.  <strong>0</strong> = passthrough.  <strong>1</strong> = full sine modulation of the gain envelope.</>}
            />
            <LabeledKnob
              label="sweep"
              value={fx.ringSweepRate}
              onChange={(v) => setFxParam("ringSweepRate", v)}
              min={0} max={20} step={0.05}
              defaultValue={0}
              formatValue={(v) =>
                v === 0      ? "off"
                : v < 0.1    ? v.toFixed(3)
                : v < 1      ? v.toFixed(2)
                : v < 10     ? v.toFixed(2)
                :              v.toFixed(1)
              }
              unit="Hz"
              disabled={!fx.ringEnabled || masterBypassed}
              // 0.001–1 Hz spans 70 % of the knob travel; 1–20 Hz the
              // remaining 30 %.  Both segments use a log curve so
              // very slow sweeps (the most musically useful range)
              // get fine resolution and aren't compressed into the
              // first few degrees.  See Knob's valueToNorm comment
              // for the mapper contract.
              valueToNorm={(v) => {
                if (v <= 0)   return 0
                if (v <= 1)   return 0.7 * (Math.log(Math.max(v, 0.001) / 0.001) / Math.log(1000))
                return 0.7 + 0.3 * (Math.log(v) / Math.log(20))
              }}
              normToValue={(n) => {
                if (n <= 0)   return 0
                if (n <= 0.7) return 0.001 * Math.pow(1000, n / 0.7)
                return Math.pow(20, (n - 0.7) / 0.3)
              }}
              // Graticule marks at the three musically meaningful
              // points on the curve: 0 (off, knob fully CCW), 1 Hz
              // (the 70 % crossover where the curve transitions from
              // log-fine to log-coarse), and 20 Hz (top end, drawn
              // as ∞ since 20 Hz feels effectively "audio-rate" — at
              // that speed the carrier sounds like a continuous
              // FM smear rather than a discrete sweep).
              markers={[
                { value: 0,  label: "0" },
                { value: 1,  label: "1" },
                { value: 20, label: "∞" },
              ]}
              tooltip={<>
                LFO speed for the carrier-frequency sweep.
                <strong> 0</strong> = sweep off (static FREQ applies).
                <strong> 0.001–1 Hz</strong> spans 70&nbsp;% of the knob
                travel for fine slow-sweep control;
                <strong> 1–20 Hz</strong> the remaining 30&nbsp;%.
                Graticule marks at <strong>0 / 1 / ∞</strong>.  LFO
                waveform set by the WAVE selector.
              </>}
            />
            <LabeledKnob
              label="low"
              value={fx.ringSweepLow}
              onChange={(v) => setFxParam("ringSweepLow", v)}
              min={20} max={2000} step={1}
              defaultValue={100}
              formatValue={(v) => v.toFixed(0)}
              unit="Hz"
              disabled={!fx.ringEnabled || masterBypassed || fx.ringSweepRate === 0}
              tooltip={<>Bottom cutoff of the sweep range.  When sweep is active, the carrier won't go below this frequency.</>}
            />
            <LabeledKnob
              label="high"
              value={fx.ringSweepHigh}
              onChange={(v) => setFxParam("ringSweepHigh", v)}
              min={20} max={2000} step={1}
              defaultValue={800}
              formatValue={(v) => v.toFixed(0)}
              unit="Hz"
              disabled={!fx.ringEnabled || masterBypassed || fx.ringSweepRate === 0}
              tooltip={<>Top cutoff of the sweep range.  When sweep is active, the carrier won't go above this frequency.</>}
            />
            <FxWaveSelector
              value={fx.ringSweepWave}
              onChange={(v) => setFxParam("ringSweepWave", v)}
              disabled={!fx.ringEnabled || masterBypassed || fx.ringSweepRate === 0}
            />
          </FxSubSection>

          <FxRule />

          {/* TREM — rate now has a Hz ⇄ ♪ toggle so users can lock
              the tremolo rate to a note value at the current BPM
              (e.g. 1/8 at 120 BPM = 4 Hz; the conversion uses
              `1000 / noteToMs(note, bpm)` so each note resolves to
              its rate in Hz). */}
          <FxSubSection
            name="trem"
            enabled={fx.tremoloEnabled}
            onToggle={() => setFxParam("tremoloEnabled", !fx.tremoloEnabled)}
            weight={3}
          >
            <KnobNoteToggle
              label="rate"
              msValue={fx.tremoloRate}
              onMsChange={(v) => setFxParam("tremoloRate", v)}
              msMin={0.05} msMax={20} msStep={0.05}
              msDefault={4}
              noteValue={fx.tremoloRateNote}
              onNoteChange={(v: NoteLabel) => setFxParam("tremoloRateNote", v)}
              mode={fx.tremoloRateMode}
              onModeChange={(m) => setFxParam("tremoloRateMode", m as "Hz" | "♪")}
              valueMode="Hz"
              valueUnit="Hz"
              valueModeLabel="Hz"
              valueFormat={(v) => v.toFixed(2)}
              noteToValue={(note, bpm) => {
                const ms = noteToMs(note, bpm)
                return ms > 0 ? 1000 / ms : 0
              }}
              disabled={!fx.tremoloEnabled || masterBypassed}
              tooltip={<>
                Tremolo LFO rate.  Toggle <strong>Hz ⇄ ♪</strong> to
                lock to a note value at the current BPM (1/4 at 120
                BPM = 2 Hz, 1/8 = 4 Hz, etc.).  In Hz mode:
                <strong> 0.05-1</strong> = slow swell,
                <strong> 2-6</strong> = classic,
                <strong> 10+</strong> = vibrato-flutter.
              </>}
            />
            <LabeledKnob
              label="depth"
              value={fx.tremoloDepth}
              onChange={(v) => setFxParam("tremoloDepth", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.tremoloEnabled || masterBypassed}
              tooltip={<>Tremolo depth.  <strong>0</strong> = bypass.  <strong>0.5</strong> = bouncy.  <strong>1</strong> = full chop.</>}
            />
            <LabeledKnob
              label="phase"
              value={fx.tremoloPhase}
              onChange={(v) => setFxParam("tremoloPhase", v)}
              min={0} max={360} step={1}
              defaultValue={0}
              formatValue={(v) => `${Math.round(v)}°`}
              showDefaultMark
              markers={[
                { value: 0,   label: "0" },
                { value: 90,  label: "¼" },
                { value: 180, label: "½" },
                { value: 270, label: "¾" },
              ]}
              disabled={!fx.tremoloEnabled || masterBypassed}
              tooltip={<>
                Phase offset of the tremolo LFO, 0–360°.  Shifts WHEN
                the modulation peak hits relative to the audio.
                Useful for time-aligning the tremolo "hits" with
                downbeats or other rhythmic elements.  Markers at
                0° (in-phase), 90° (¼ period), 180° (anti-phase),
                270° (¾ period).
              </>}
            />
          </FxSubSection>

        </div>
      </div>

      {/* ── TIME PANEL: cool steel zone for time-space effects ───── */}
      <div className={cn(
        "fx-panel-time px-3 py-2 transition-opacity",
        masterBypassed && "opacity-50",
      )}>
        <FxPanelTitle name="time / space" />
        <div className="flex items-stretch gap-1 flex-wrap">

          {/* DELAY (time control has ms ⇄ ♪ note-mode toggle) */}
          <FxSubSection
            name="delay"
            enabled={fx.delayEnabled}
            onToggle={() => setFxParam("delayEnabled", !fx.delayEnabled)}
            weight={3}
          >
            <KnobNoteToggle
              label="time"
              msValue={fx.delayTime * 1000}
              onMsChange={(v) => setFxParam("delayTime", v / 1000)}
              msMin={0} msMax={2000} msStep={1}
              msDefault={300}
              noteValue={fx.delayTimeNote}
              onNoteChange={(v: NoteLabel) => setFxParam("delayTimeNote", v)}
              mode={fx.delayTimeMode}
              onModeChange={(m) => setFxParam("delayTimeMode", m as "ms" | "♪")}
              disabled={!fx.delayEnabled || masterBypassed}
              tooltip={<>
                Delay time, 0–2000 ms.  Toggle <strong>ms ⇄ ♪</strong> to lock the delay to the detected BPM (e.g. 1/8 = eighth-note delay at the current tempo).  In note mode the value re-syncs whenever the BPM override or auto-detection changes.
              </>}
            />
            <LabeledKnob
              label="feedback"
              value={fx.delayFb}
              onChange={(v) => setFxParam("delayFb", v)}
              min={0} max={0.95} step={0.01}
              defaultValue={0.35}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.delayEnabled || masterBypassed}
              tooltip={<>Delay feedback.  <strong>0</strong> = single repeat (loop disconnected).  <strong>0.5</strong> ≈ 6 echoes.  <strong>0.9+</strong> = drone.  Capped at 0.95 to prevent runaway.  Default tick at 0.35.</>}
            />
            <LabeledKnob
              label="mix"
              value={fx.delayMix}
              onChange={(v) => setFxParam("delayMix", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.delayEnabled || masterBypassed}
              tooltip={<>Wet/dry blend.  <strong>0</strong> = bypass.  <strong>0.5</strong> = equal.  <strong>1</strong> = wet only.</>}
            />
          </FxSubSection>

          <FxRule />

          {/* PHASER */}
          <FxSubSection
            name="phaser"
            enabled={fx.phaserEnabled}
            onToggle={() => setFxParam("phaserEnabled", !fx.phaserEnabled)}
            weight={2}
          >
            <LabeledKnob
              label="rate"
              value={fx.phaseRate}
              onChange={(v) => setFxParam("phaseRate", v)}
              min={0.05} max={10} step={0.05}
              defaultValue={1.0}
              formatValue={(v) => v.toFixed(2)}
              unit="Hz"
              disabled={!fx.phaserEnabled || masterBypassed}
              tooltip={<>LFO sweep rate.  <strong>0.05-0.5</strong> = cosmic sweep.  <strong>1-3</strong> = classic phaser.  <strong>5+</strong> = throbbing.</>}
            />
            <LabeledKnob
              label="depth"
              value={fx.phaseDepth}
              onChange={(v) => setFxParam("phaseDepth", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.phaserEnabled || masterBypassed}
              tooltip={<>Phaser intensity — controls LFO sweep range AND wet/dry mix.  <strong>0</strong> = bypass.  <strong>1</strong> = full.</>}
            />
          </FxSubSection>

          <FxRule />

          {/* PANNER — auto-pan with mix + sweep (rate/low/high/wave),
              same LFO pattern as the ring-mod sweep but driving a
              StereoPannerNode's pan position instead of the ring
              carrier frequency.  Sits POST-reverb so the panner
              moves the entire processed signal in the stereo
              field. */}
          <FxSubSection
            name="panner"
            enabled={fx.pannerEnabled}
            onToggle={() => setFxParam("pannerEnabled", !fx.pannerEnabled)}
            weight={5}
          >
            <LabeledKnob
              label="mix"
              value={fx.pannerMix}
              onChange={(v) => setFxParam("pannerMix", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.pannerEnabled || masterBypassed}
              tooltip={<>
                Wet/dry blend.  <strong>0</strong> = bypass (signal
                stays centered).  <strong>0.5</strong> = halfway
                between centered and full pan.  <strong>1</strong>
                = full pan effect.
              </>}
            />
            <LabeledKnob
              label="sweep"
              value={fx.pannerSweepRate}
              onChange={(v) => setFxParam("pannerSweepRate", v)}
              min={0} max={20} step={0.05}
              defaultValue={0.5}
              formatValue={(v) =>
                v === 0      ? "off"
                : v < 0.1    ? v.toFixed(3)
                : v < 1      ? v.toFixed(2)
                : v < 10     ? v.toFixed(2)
                :              v.toFixed(1)
              }
              unit="Hz"
              disabled={!fx.pannerEnabled || masterBypassed}
              // Same 70/30 log taper as the ring sweep — slow rates
              // (the most musically useful range for auto-pan) get
              // most of the knob travel.
              valueToNorm={(v) => {
                if (v <= 0)   return 0
                if (v <= 1)   return 0.7 * (Math.log(Math.max(v, 0.001) / 0.001) / Math.log(1000))
                return 0.7 + 0.3 * (Math.log(v) / Math.log(20))
              }}
              normToValue={(n) => {
                if (n <= 0)   return 0
                if (n <= 0.7) return 0.001 * Math.pow(1000, n / 0.7)
                return Math.pow(20, (n - 0.7) / 0.3)
              }}
              markers={[
                { value: 0,  label: "0" },
                { value: 1,  label: "1" },
                { value: 20, label: "∞" },
              ]}
              tooltip={<>
                Pan-sweep rate in Hz. <strong>0</strong> = sweep off
                (pan parks at the midpoint of low/high).
                <strong> 0.001–1 Hz</strong> spans 70% of knob travel
                for slow auto-pan; <strong>1–20 Hz</strong> the
                remaining 30%.  At 20 Hz the panning is at audio rate
                — borderline ring-mod-of-pan territory.
              </>}
            />
            <LabeledKnob
              label="L"
              value={fx.pannerSpreadL}
              onChange={(v) => setFxParam("pannerSpreadL", v)}
              min={0} max={1} step={0.01}
              defaultValue={1}
              formatValue={(v) =>
                v === 0 ? "C"
                : v === 1 ? "L"
                : `L${v.toFixed(2)}`
              }
              showDefaultMark
              // Invert the visual mapping: high value (= more left
              // spread) renders the indicator pointing LEFT (CCW),
              // low value renders pointing RIGHT (CW toward center).
              // Without this inversion the L knob "increases to the
              // right" which is cognitively dissonant for a control
              // that reaches further LEFT as it grows.  Pairs with
              // the R knob's natural "increases to the right"
              // behavior so at default both indicators point AWAY
              // from center, and at 0 both point TOWARD center.
              valueToNorm={(v) => 1 - Math.max(0, Math.min(1, v))}
              normToValue={(n) => 1 - Math.max(0, Math.min(1, n))}
              invertArc
              disabled={!fx.pannerEnabled || masterBypassed}
              tooltip={<>
                Spread to the LEFT — how far the pan reaches from
                center toward full L.  <strong>0</strong> = pan
                never crosses center to the left (right-side or
                center-only sweep).  <strong>1</strong> = full L
                reach (-1).  Combine with R for asymmetric sweeps
                (e.g., L=0.3, R=1 keeps movement biased toward the
                right channel).  Knob is inverted so the indicator
                points LEFT when reaching far left.
              </>}
            />
            <LabeledKnob
              label="R"
              value={fx.pannerSpreadR}
              onChange={(v) => setFxParam("pannerSpreadR", v)}
              min={0} max={1} step={0.01}
              defaultValue={1}
              formatValue={(v) =>
                v === 0 ? "C"
                : v === 1 ? "R"
                : `R${v.toFixed(2)}`
              }
              showDefaultMark
              disabled={!fx.pannerEnabled || masterBypassed}
              tooltip={<>
                Spread to the RIGHT — mirror of L.  <strong>0</strong>
                = pan never crosses center to the right.
                <strong> 1</strong> = full R reach (+1).
                When L and R differ, the sweep is asymmetric and
                its midpoint shifts to (R-L)/2.
              </>}
            />
            <FxWaveSelector
              value={fx.pannerSweepWave}
              onChange={(v) => setFxParam("pannerSweepWave", v)}
              disabled={!fx.pannerEnabled || masterBypassed}
            />
          </FxSubSection>

          <FxRule />

          {/* REVERB */}
          <FxSubSection
            name="reverb"
            enabled={fx.reverbEnabled}
            onToggle={() => setFxParam("reverbEnabled", !fx.reverbEnabled)}
            weight={3}
          >
            <LabeledKnob
              label="size"
              value={fx.reverbSize}
              onChange={(v) => setFxParam("reverbSize", v)}
              min={0.1} max={5} step={0.05}
              defaultValue={1.5}
              formatValue={(v) => v.toFixed(2)}
              unit="s"
              disabled={!fx.reverbEnabled || masterBypassed}
              tooltip={<>Reverb tail length.  <strong>0.1-0.5</strong> = booth.  <strong>1-2</strong> = small room.  <strong>3+</strong> = hall / cathedral.</>}
            />
            <LabeledKnob
              label="decay"
              value={fx.reverbDecay}
              onChange={(v) => setFxParam("reverbDecay", v)}
              min={1} max={6} step={0.1}
              defaultValue={2.5}
              formatValue={(v) => v.toFixed(1)}
              disabled={!fx.reverbEnabled || masterBypassed}
              tooltip={<>Decay shape exponent.  <strong>1</strong> = linear.  <strong>2-3</strong> = natural room.  <strong>5-6</strong> = bunker.</>}
            />
            <LabeledKnob
              label="mix"
              value={fx.reverbMix}
              onChange={(v) => setFxParam("reverbMix", v)}
              min={0} max={1} step={0.01}
              defaultValue={0}
              formatValue={(v) => v.toFixed(2)}
              showDefaultMark
              disabled={!fx.reverbEnabled || masterBypassed}
              tooltip={<>Reverb wet/dry mix.  <strong>0</strong> = bypass.  <strong>1</strong> = wet only.</>}
            />
          </FxSubSection>

        </div>
      </div>

      {/* ── ACTION ROW: reset + revert-to-dry on the LEFT, burn FX +
          status pinned to the RIGHT via ml-auto.  Layout mirrors
          OUTPUT (slurmify) and VIDEO (render) — primary action sits
          flush right, secondary/cleanup controls on the left, so the
          eye lands on the same column across all three rack modules.
          Sits in normal padding (no negative margins) so it reads as
          part of the rack chassis rather than another panel. */}
      <div className="flex flex-col gap-2 px-3 py-3">
        <div className="flex items-center gap-3">
          {/* LEFT — secondary controls (reset, revert-to-dry).  Reset
              is always visible; revert-to-dry only appears once a
              burn exists (so the user has something to revert FROM). */}
          <Tip text="Set every FX knob back to defaults. Live preview becomes effective bypass. Doesn't affect any already-burned file.">
            <Button size="sm" variant="ghost" className="text-slurm-muted hover:text-slurm-fg" onClick={resetFx}>
              <RotateCcw className="!h-3 !w-3" />
              reset
            </Button>
          </Tip>

          {burnedId && !isBurning && (
            <Tip text="Drop the burned-FX file and play the dry slurm output again. Knob settings stay; only the bake is reverted.">
              <Button size="sm" variant="ghost" className="text-slurm-muted hover:text-slurm-fg" onClick={clearBurn}>
                revert to dry
              </Button>
            </Tip>
          )}

          {/* RIGHT — primary "burn FX" action + inline progress/error.
              ml-auto pushes the whole group flush against the panel's
              right edge, matching the slurmify (OUTPUT) and render
              (VIDEO) buttons' position so the user has a consistent
              "primary action lives on the right" mental model across
              all three modules. */}
          <div className="ml-auto flex items-center gap-3">
            {isBurning && (
              <span className="text-[11px] tabular-nums text-slurm-muted">
                {burnDesc || "starting…"}
              </span>
            )}

            {burnError && !isBurning && (
              <span className="text-[11px] text-slurm-danger">{burnError}</span>
            )}

            <Tip
              text={
                isBurning
                  ? "A burn-FX job is already running.  Wait for it to finish."
                  : burnTarget
                    ? <>Bake the current FX into a NEW audio file from the {burnTarget}.  <strong>Note:</strong> tremolo, reverb, dist gain/shape/tone, and ring-sweep are LIVE-PREVIEW ONLY for now — the backend burn applies the original four effects (drive / ring / delay / phaser).  Live FX still applies on top of the burned file.</>
                    : "Drop a file or run slurmify first."
              }
            >
              <Button
                size="default"
                variant="default"
                disabled={isBurning || !burnTarget}
                onClick={() => void burnRun()}
                className="min-w-[120px]"
              >
                {isBurning ? (<><Loader2 className="animate-spin" />burning…</>) : (<><Flame />burn FX</>)}
              </Button>
            </Tip>
          </div>
        </div>

        {isBurning && (<Progress value={Math.round(burnProg * 100)} />)}

        {isBurning && (
          <div className="flex justify-center py-1">
            <Dancer width={120} caption={burnDesc || "starting…"} />
          </div>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────
// FX MODULE HELPER COMPONENTS — Roland Chorus-Echo-inspired interior
// ──────────────────────────────────────────────────────────────────────
//
// These helpers compose the FxBody's two-zone faceplate.  All visual
// classes (.fx-rail, .fx-panel-mod, .fx-panel-time, .fx-subsection-
// header, .fx-subsection-rule, .fx-modelplate) live in globals.css.
// ──────────────────────────────────────────────────────────────────────

/** Top-rail strip with the Roland-style yellow pinstripe.  Holds the
 *  master FX bypass on the left and a stamped "SLURM·FX mk1" model
 *  plate on the right.  Sits flush against the bottom edge of the
 *  rack module header — the rack-deep-blue header above + the yellow
 *  pinstripe below makes the seam read as the painted bezel of a
 *  real piece of gear. */
function FxTopRail({
  bypass,
  onToggleBypass,
}: {
  bypass:         boolean
  onToggleBypass: () => void
}) {
  return (
    <div className="fx-rail relative flex items-center gap-3 px-3 py-1.5">
      <Tip
        text={
          <>
            Master FX bypass.  When <strong>ON</strong> (LED green),
            the chain is active and every per-effect bypass is
            honored independently.  When <strong>OFF</strong>, every
            effect collapses to passthrough — your dry slurm plays
            back unaltered.  Useful for A/B comparison.
          </>
        }
      >
        <button
          type="button"
          role="switch"
          aria-checked={!bypass}
          onClick={onToggleBypass}
          className={cn(
            "flex items-center gap-2 px-2 py-0.5 rounded-sm",
            "border transition-all select-none",
            !bypass
              ? "border-slurm-ok/60 bg-black/40 text-slurm-fg"
              : "border-slurm-border-2 bg-black/30 text-slurm-muted",
          )}
        >
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{
              backgroundColor: !bypass ? "var(--slurm-ok)" : "var(--slurm-border-2)",
              boxShadow:       !bypass ? "0 0 6px var(--slurm-ok)" : "inset 0 0 2px rgba(0,0,0,0.5)",
            }}
          />
          <span className="panel-label text-[10px]">fx chain</span>
          <span className="lcd text-[12px] tabular-nums">
            {!bypass ? "ACTIVE" : "BYPASS"}
          </span>
        </button>
      </Tip>

      <div className="flex-1" />

      {/* Decorative model plate — stamped onto the right end of the
          rail like a Roland nameplate.  Click does nothing; this is
          pure visual identity. */}
      <div
        className="fx-modelplate flex items-center gap-1 px-2 py-0.5 rounded-sm"
        aria-hidden="true"
      >
        <span className="panel-label text-[9px] text-slurm-cyan">SLURM·FX</span>
        <span className="panel-label text-[9px] text-white/35">— mk1</span>
      </div>
    </div>
  )
}

/** Etched panel-name strip at the top of each color zone.  Small,
 *  decorative dual-rule pattern (—— modulation ——) so the panel
 *  identity reads without visual weight competing with the section
 *  sub-headers below. */
function FxPanelTitle({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2 mb-1.5">
      <span className="h-px flex-1 bg-white/10" />
      <span className="panel-label text-[9px] text-white/50">{name}</span>
      <span className="h-px flex-1 bg-white/10" />
    </div>
  )
}

/** Single-effect sub-section.  The header bar is itself the
 *  per-effect bypass toggle — click anywhere on it (LED + name)
 *  to flip enable/disable.  The body slot below holds the section's
 *  knobs and selectors via children.
 *
 *  `weight` controls flex-grow so a section's width tracks its
 *  control count (DIST=4 knobs, RING=6 knobs, TREM=2 knobs → DIST
 *  gets 4/12 of the panel, RING gets 6/12, TREM gets 2/12).  Without
 *  this, every section took 1/N of the panel regardless of content,
 *  which left big gutters in DIST/TREM and crammed RING. */
function FxSubSection({
  name,
  enabled,
  onToggle,
  children,
  tooltip,
  weight = 1,
}: {
  name:    string
  enabled: boolean
  onToggle: () => void
  children: React.ReactNode
  tooltip?: React.ReactNode
  weight?: number
}) {
  return (
    <div
      className="flex min-w-0 flex-col gap-1"
      style={{ flexGrow: weight, flexShrink: 1, flexBasis: 0 }}
    >
      <Tip
        text={
          tooltip ?? (
            <>
              Per-effect bypass for the <strong>{name}</strong> stage.
              Click anywhere on this header to toggle.  Independent of
              the master FX bypass at the top of the module.
            </>
          )
        }
      >
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={`${name} bypass`}
          onClick={onToggle}
          className={cn(
            "fx-subsection-header flex items-center gap-2 px-2 py-1",
            "transition-opacity select-none cursor-pointer",
            !enabled && "opacity-60",
          )}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{
              backgroundColor: enabled ? "var(--slurm-ok)" : "var(--slurm-border-2)",
              boxShadow: enabled
                ? "0 0 4px var(--slurm-ok)"
                : "inset 0 0 1px rgba(0,0,0,0.5)",
            }}
          />
          <span className="panel-label text-[10px] text-white/85">{name}</span>
          {!enabled && (
            <span className="panel-label text-[8px] text-slurm-warn ml-auto">
              byp
            </span>
          )}
        </button>
      </Tip>

      <div className="flex flex-wrap items-start gap-x-1 gap-y-2 px-1 pt-1 pb-1">
        {children}
      </div>
    </div>
  )
}

/** Vertical hairline divider between sub-sections in the same color
 *  panel.  Faded at top + bottom (gradient defined in
 *  .fx-subsection-rule) so the rule doesn't slam into the panel
 *  edges.  self-stretch makes it span the full height of the
 *  flex-stretch row regardless of which sibling is tallest. */
function FxRule() {
  return <div className="fx-subsection-rule w-px shrink-0 mx-1 self-stretch" />
}

/** 4-chip distortion shape selector — fits in a knob-cell-width
 *  vertical stack so it sits cleanly inline with the other knobs
 *  in the DIST sub-section. */
function FxShapeSelector({
  value,
  onChange,
  disabled,
}: {
  value:    DistShape
  onChange: (v: DistShape) => void
  disabled?: boolean
}) {
  const shapes: { value: DistShape; label: string; desc: string }[] = [
    { value: "soft", label: "soft", desc: "Tanh saturation — smooth tube-like color." },
    { value: "hard", label: "hard", desc: "Hard-clip to threshold — aggressive edge." },
    { value: "fold", label: "fold", desc: "Wavefolder — sin(k·x) wraps around as drive increases." },
    { value: "fuzz", label: "fuzz", desc: "Asymmetric half-rectified — transistor fuzz feel." },
  ]
  // Layout: current-value LCD readout on TOP, button column in the
  // MIDDLE, "shape" panel label on the BOTTOM.  Putting the value
  // at the top lets the user see "what is this set to" at a glance
  // before hunting through the four small buttons; the label at the
  // bottom reads as a name-plate, matching the look-and-feel of a
  // hardware module.  (Previous order was buttons → label → value,
  // which left the label sandwiched between two visually noisy
  // elements and made the panel-label's 0.18em letter-spacing read
  // as broken stretching.)
  return (
    <div className={cn(
      "flex w-[76px] shrink-0 flex-col items-center gap-1 select-none",
      disabled && "opacity-50",
    )}>
      <div className="lcd text-[11px] text-slurm-fg uppercase">{value}</div>
      <div className="flex h-14 flex-col gap-0.5 items-stretch w-full px-1">
        {shapes.map((s) => {
          const active = value === s.value
          return (
            <Tip key={s.value} text={s.desc}>
              <button
                type="button"
                onClick={() => onChange(s.value)}
                disabled={disabled}
                className={cn(
                  "flex-1 rounded text-[9px] uppercase tracking-wider",
                  "border transition-colors",
                  active
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-slurm-border-2 text-slurm-muted hover:text-slurm-fg",
                )}
              >
                {s.label}
              </button>
            </Tip>
          )
        })}
      </div>
      <div className="panel-label text-[10px] text-slurm-muted">shape</div>
    </div>
  )
}

/** 4-chip ring-sweep wave selector.  Same vertical-stack pattern as
 *  FxShapeSelector but for sine/saw/square/noise, sized to align
 *  with the other knobs in the RING sub-section. */
function FxWaveSelector({
  value,
  onChange,
  disabled,
}: {
  value:    SweepWave
  onChange: (v: SweepWave) => void
  disabled?: boolean
}) {
  const waves: { value: SweepWave; label: string; desc: string }[] = [
    { value: "sine",   label: "sin", desc: "Smooth periodic sweep — gentle wobble." },
    { value: "saw",    label: "saw", desc: "Ramp up + sudden reset — pulse-train chase." },
    { value: "square", label: "sqr", desc: "On/off step toggle — chops between low and high." },
    { value: "noise",  label: "nse", desc: "Random wandering — band-limited noise modulation." },
  ]
  // Same value-on-top → buttons → label-on-bottom order as
  // FxShapeSelector — see that comment for the reasoning.  Keeps the
  // two selectors visually consistent across the FX rack.
  return (
    <div className={cn(
      "flex w-[76px] shrink-0 flex-col items-center gap-1 select-none",
      disabled && "opacity-50",
    )}>
      <div className="lcd text-[11px] text-slurm-fg uppercase">{value}</div>
      <div className="flex h-14 flex-col gap-0.5 items-stretch w-full px-1">
        {waves.map((w) => {
          const active = value === w.value
          return (
            <Tip key={w.value} text={w.desc}>
              <button
                type="button"
                onClick={() => onChange(w.value)}
                disabled={disabled}
                className={cn(
                  "flex-1 rounded text-[9px] uppercase tracking-wider",
                  "border transition-colors",
                  active
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-slurm-border-2 text-slurm-muted hover:text-slurm-fg",
                )}
              >
                {w.label}
              </button>
            </Tip>
          )
        })}
      </div>
      <div className="panel-label text-[10px] text-slurm-muted">wave</div>
    </div>
  )
}

// (Legacy effects-grid + old FxSection helper removed in the
//  Roland Chorus-Echo redesign.  The new FxBody above uses
//  FxTopRail / FxPanelTitle / FxSubSection / FxRule /
//  FxShapeSelector / FxWaveSelector exclusively.)

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
  const isSlurming      = useSlurmStore((s) => s.isRunning)
  const burnedFileId    = useFxStore((s) => s.burnedFileId)
  const backendUrl      = useBackendUrl()

  const { run: renderRun } = useRenderVideoJob()
  // Auto-slurm-before-render: if the user clicks render with no
  // existing slurm output (and no burned-FX file either), kick off a
  // slurmify run with current settings FIRST, then chain into render.
  // Reads the freshly-created output via slurmStore.getState() inside
  // useRenderVideoJob.run so we don't need to plumb it through here.
  const { run: slurmRun }  = useSlurmifyJob()

  const [saveStatus, setSaveStatus] = useState<{
    kind: "saving" | "saved" | "error"
    message?: string
  } | null>(null)

  // (The old `renderSourceLabel` derivation lived here before the
  //  audio-source picker landed — superseded by `effectiveSourceLabel`
  //  below, which respects the user's explicit clean / FX-burned /
  //  auto choice.)

  // Render-button click handler.  Two paths:
  //   (a) audio already exists (slurm output or burned FX) → render
  //       directly using whatever's there.
  //   (b) only the raw source exists → run slurmify first, await
  //       the new output, then render.  The slurm progress shows in
  //       the OUTPUT module; the video progress kicks in afterwards.
  // useRenderVideoJob.run reads slurmStore.output via getState() at
  // call time, so the freshly-created slurm output is picked up
  // automatically without needing to pass anything through here.
  const handleRender = async () => {
    const hasAudio = !!burnedFileId || !!slurmOutput?.output_id
    if (!hasAudio) {
      const slurmResult = await slurmRun()
      if (!slurmResult) {
        // Slurmify failed — error is already in slurmStore.error and
        // visible in the OUTPUT module.  Don't proceed to render.
        return
      }
    }
    await renderRun()
  }

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

  // Effective audio-source label for tooltip/inline status — what
  // /render-video will actually use given the user's audioSource pick
  // and what files exist.  Mirrors the resolution logic inside
  // useRenderVideoJob.run so the UI doesn't lie to the user.
  //
  // Default is "fx-burned" (W5b: FX-on-by-default for YouTube
  // renders) — the legacy "auto" value still rolls through this
  // branch as an alias.  When fx-burned is the chosen mode and no
  // burn exists yet, useRenderVideoJob auto-runs /burn-fx FIRST
  // before /render-video, so the UI label reflects that intent
  // ("FX-burned output (will auto-burn)") instead of suggesting
  // the render is blocked.
  const audioSource = meta.audioSource ?? "fx-burned"
  const includeFx = audioSource !== "slurm"   // legacy "auto" treated as include-FX
  const effectiveSourceLabel: string | null = (() => {
    if (audioSource === "slurm") {
      return slurmOutput ? "slurm output (dry)" : sourceFile ? "auto-slurm + render (dry)" : null
    }
    // fx-burned (default) or legacy "auto"
    if (burnedFileId) return "FX-burned output"
    if (slurmOutput || sourceFile) return "FX-burned output (will auto-burn)"
    return null
  })()

  return (
    <div className="flex flex-col gap-2">
      {/* Top action bar — title + creator + include-source toggle +
          audio-source select on the LEFT, render button + status on
          the RIGHT.  Same layout philosophy as OutputBody: collapse a
          stack of form rows into a single header line so the rack
          stays short and the visual flow tracks left → right →
          (button) → preview-below.  flex-wrap lets the trailing
          controls drop to a second line on narrow viewports rather
          than overflow. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Title — used in the MP4 metadata + safe-title filename slug.
            Shrunk to 11rem (was 14) so the whole row fits on a single
            horizontal line — anything truly long can still be typed,
            it just scrolls within the input. */}
        <LabeledTextbox
          label="title"
          value={meta.title}
          onChange={(v) => setMetadata("title", v)}
          type="text"
          placeholder="my slurm"
          inputWidth="11rem"
          disabled={isRendering}
          compactLabel
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
          inputWidth="11rem"
          disabled={isRendering}
          compactLabel
          tooltip={
            <>
              Artist name shown in YouTube + media-player UIs. Embedded
              into the MP4's <code>artist</code> metadata atom. Leave
              blank → defaults to "Subvoyant SIENA Slurmer".
            </>
          }
        />

        {/* Audio source — short option labels.  The two-option model
            lands the W5b FX-on-by-default UX change: FX-burned is the
            default; "clean slurm (dry)" is the explicit opt-out.
            (The legacy "auto" value was the old default and still
            survives in persisted state from v0.2.0.0; useRenderVideoJob
            treats it as an alias for "fx-burned".  Not exposed as a
            picker option to avoid confusion — anyone who had "auto"
            persisted gets the new default behavior automatically.)
            See useRenderVideoJob.run for the matching resolution
            logic, and videoStore.ts for the field-level history. */}
        <LabeledSelect
          label="audio"
          value={meta.audioSource === "auto" ? "fx-burned" : meta.audioSource}
          onValueChange={(v) => setMetadata("audioSource", v as "auto" | "slurm" | "fx-burned")}
          options={[
            { value: "fx-burned", label: "FX-burned (default)" },
            { value: "slurm",     label: "clean slurm (dry)" },
          ]}
          triggerWidth="11rem"
          disabled={isRendering}
          compactLabel
          tooltip={
            <>
              Which audio track gets encoded into the MP4.{" "}
              <strong>FX-burned (default)</strong> = bake the FX chain
              into the rendered audio. If you've already clicked
              "burn FX" the existing burn is reused; otherwise the
              render auto-runs burn-fx first using the current FX
              knob settings, then encodes the result.{" "}
              <strong>clean slurm (dry)</strong> = explicit opt-out —
              encode the dry slurm output, ignoring any FX dialed up
              in the FX module. Useful when you want a clean reference
              cut alongside an effected one.
            </>
          }
        />

        {/* Include-source toggle — affects PATCH JSON only.
            compactLabel so the switch reads as anchored to its label
            (recovers ~90 px of horizontal slack vs the default
            128 px label slot — the difference between fitting on
            one line and wrapping the render button). */}
        <LabeledSwitch
          label="include src"
          checked={meta.includeSourceFilename}
          onCheckedChange={(v) => setMetadata("includeSourceFilename", v)}
          disabled={isRendering}
          compactLabel
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

        {/* Render button + status — pinned to the right via ml-auto
            so it always sits flush with the panel edge regardless of
            how wide the metadata controls render.  When the user has
            no slurm output yet AND audio source is "auto" or
            "slurm", the button label flips to "slurm + render" and
            the click handler chains the two jobs. */}
        <div className="ml-auto flex items-center gap-3">
          <Tip
            text={
              isRendering
                ? "A render is in progress. Wait for it to finish before queueing another."
                : isSlurming
                  ? "An auto-slurm is running first; the render kicks in as soon as it finishes."
                  : !effectiveSourceLabel
                    ? "Drop a file first — render-video needs an audio source."
                    : !includeFx && slurmOutput
                      ? <>Render a 1920×1080 MP4 with the looping slurmify animation + your <strong>clean slurm output</strong> (no FX) as the audio track.</>
                      : burnedFileId
                        ? <>Render a 1920×1080 MP4 with the looping slurmify animation + your <strong>FX-burned output</strong> as the audio track. Stream-copied video + AAC audio = renders in seconds.</>
                        : slurmOutput || sourceFile
                          ? <>FX are <strong>on by default</strong>: clicking will burn the current FX chain into the audio first, then render the MP4 with the burned result.  Pick "clean slurm (dry)" in the audio selector to opt out.</>
                          : <>No audio source yet — clicking will <strong>slurmify with the current settings first</strong>, then bake FX, then render the video.</>
            }
          >
            <Button
              size="default"
              variant="default"
              disabled={isRendering || isSlurming || !effectiveSourceLabel}
              onClick={() => void handleRender()}
              className="min-w-[180px]"
            >
              {isSlurming ? (
                <>
                  <Loader2 className="animate-spin" />
                  slurming first…
                </>
              ) : isRendering ? (
                <>
                  <Loader2 className="animate-spin" />
                  rendering…
                </>
              ) : !slurmOutput && !burnedFileId && sourceFile && !includeFx ? (
                <>
                  <Film />
                  slurm + render MP4
                </>
              ) : (
                <>
                  <Film />
                  render YouTube MP4
                </>
              )}
            </Button>
          </Tip>

          {isRendering && (
            <span className="text-[11px] tabular-nums text-slurm-muted">
              {renderDesc || "starting…"}
            </span>
          )}

          {renderError && !isRendering && (
            <span className="text-[11px] text-slurm-danger">{renderError}</span>
          )}
        </div>
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
