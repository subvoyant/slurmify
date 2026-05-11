// ──────────────────────────────────────────────────────────────────────
// src/stores/fxStore.ts — FX chain params + burn-job state
// ──────────────────────────────────────────────────────────────────────
//
// Companion to slurmStore.  Holds the 8 FX-chain knob values that
// drive BOTH the live Web Audio preview (useFxChain hook) AND the
// /burn-fx export action (useBurnFxJob hook).  Same field names the
// backend's BurnFxRequest expects, so building the request body is a
// one-line spread.
//
// What we persist (localStorage):
//   • params — sticky preference; the user's last knob positions come
//     back on reload.
//
// What we DON'T persist:
//   • job state — purely transient.
//   • burnedFileId — references a backend-side file that's gone after
//     a sidecar restart; persisting would surface ghost references.
//
// Topology (matches v0.1.6's _fxP keys + ui_assets.py FX chain):
//   src → distortion → ringMod → delay → phaser → destination
//
// Field mapping to BurnFxRequest:
//   distDrive  → dist_drive       phaseRate   → phase_rate
//   ringFreq   → ring_freq        phaseDepth  → phase_depth
//   ringDepth  → ring_depth
//   delayTime  → delay_sec
//   delayFb    → delay_fb
//   delayMix   → delay_mix
//
// Camel→snake mapping is applied in useBurnFxJob.buildRequestBody so
// store consumers can stay in idiomatic JS naming.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

// ── Param shape — matches v0.1.6's _fxP one-for-one ──────────────────
//
// All values are normalized to a 0–1 range EXCEPT the three "natural
// unit" params:
//   • ringFreq  — Hz (carrier oscillator frequency)
//   • delayTime — seconds (delay line length, 0–2)
//   • phaseRate — Hz (LFO rate driving phaser sweep)
// These three deserve real units in the UI because their useful ranges
// span more than one decade (a 0–1 normalized knob would flatten the
// entire usable space into a tiny rotation arc).

/** Distortion curve shape — controls the WaveShaper's character.
 *  Each shape uses the same `distDrive` knob for intensity but yields
 *  a different sonic signature:
 *    • soft  — tanh, smooth tube-like saturation (legacy default)
 *    • hard  — clipped to ±1, aggressive edge
 *    • fold  — wavefolding, sine-shaped wrap-around
 *    • fuzz  — half-wave rectified asymmetric clipping (transistor fuzz)
 */
export type DistShape = "soft" | "hard" | "fold" | "fuzz"

/** Ring-mod sweep waveform — drives the LFO that modulates the
 *  carrier frequency over time.  sine/saw/square map to
 *  OscillatorNode types directly; noise uses a band-limited noise
 *  source for random wandering ("sample-and-hold-ish" character). */
export type SweepWave = "sine" | "saw" | "square" | "noise"

export interface FxParams {
  // ── Master ───────────────────────────────────────────────────────
  /** Master FX bypass.  When true, every effect is set to a unit-
   *  passthrough state — signal flows from input straight to output
   *  unchanged (modulo numerical noise from oscillators that stay
   *  running but at zero depth). */
  bypass: boolean

  // ── Distortion (WaveShaper with selectable curve shape) ──────────
  /** Per-effect bypass switch. */
  distEnabled: boolean
  /** Pre-WaveShaper input gain in dB.  -24 to +24.  Adds drive
   *  upstream so even "soft" shapes can be pushed hard at high gain. */
  distGain: number
  /** Drive amount, 0–1.  At 0, the curve is identity (pass-through). */
  distDrive: number
  /** Curve shape — see DistShape comment above. */
  distShape: DistShape
  /** Tone tilt EQ, -1 (dark) to +1 (bright).  Drives a single
   *  high-shelf BiquadFilter applied AFTER the distortion stage. */
  distTone: number

  // ── Ring modulator (sine osc → gain.gain) ─────────────────────────
  /** Per-effect bypass switch. */
  ringEnabled: boolean
  /** Carrier frequency in Hz, used as the static value when the sweep
   *  is off (ringSweepRate = 0).  When the sweep is on, this knob is
   *  ignored and the carrier oscillates between low/high cutoffs. */
  ringFreq: number
  /** Modulation depth.  0 = bypass (gain stays at 1).  1 = full ring
   *  modulation. */
  ringDepth: number
  /** Ring-mod LFO sweep speed in Hz.  When > 0, the carrier
   *  frequency sweeps between ringSweepLow and ringSweepHigh at this
   *  rate (overriding the static ringFreq).  0 = sweep off, static
   *  freq applies. */
  ringSweepRate: number
  /** Rate-mode toggle.  "Hz" = use ringSweepRate as-is.  "♪" =
   *  compute Hz from ringSweepRateNote at the current effective BPM
   *  (e.g. "1/4" at 120 BPM = 2 Hz).  Mirrors the tremoloRateMode /
   *  delayTimeMode pattern; same note→Hz formula
   *  (`1000 / noteToMs(note, bpm)`).  Added in v0.3 (PLAN_FX_RACK_V0.3.md). */
  ringSweepRateMode: "Hz" | "♪"
  /** Note fraction string used when ringSweepRateMode is "♪".  Same
   *  grammar as src/lib/note-mode.ts. */
  ringSweepRateNote: string
  /** Bottom cutoff of the sweep range in Hz.  Carrier won't go
   *  below this when sweep is active. */
  ringSweepLow: number
  /** Top cutoff of the sweep range in Hz.  Carrier won't go above
   *  this when sweep is active. */
  ringSweepHigh: number
  /** Sweep waveform type.  sine/saw/square map directly to
   *  OscillatorNode types; noise uses a band-limited random source
   *  for "sample-and-hold-ish" wandering. */
  ringSweepWave: SweepWave

  // ── Tremolo (sine osc → gain pre-multiplier) ─────────────────────
  /** Per-effect bypass switch. */
  tremoloEnabled: boolean
  /** LFO rate in Hz.  0.05 = slow swell.  5+ = vibrato-like flutter. */
  tremoloRate: number
  /** Rate-mode toggle.  "Hz" = use tremoloRate as-is.  "♪" = compute
   *  Hz from tremoloRateNote at the current effective BPM (e.g.
   *  "1/8" at 120 BPM = 4 Hz).  The note→Hz conversion is
   *  `1000 / noteToMs(note, bpm)`. */
  tremoloRateMode: "Hz" | "♪"
  /** Note fraction string used when tremoloRateMode is "♪".
   *  Same grammar as src/lib/note-mode.ts. */
  tremoloRateNote: string
  /** Modulation depth, 0–1.  At 1, signal is fully modulated (silence
   *  at LFO troughs).  0.5 is a classic "bouncing" tremolo. */
  tremoloDepth: number
  /** Phase offset in degrees, 0–360.  Shifts when the LFO peak hits
   *  relative to the audio.  Implementation: a DelayNode after the
   *  LFO delays the modulation signal by (phase/360) × period.  At
   *  rate=4 Hz, phase=90° introduces a 62.5 ms delay on the LFO
   *  signal.  Useful for time-aligning tremolo "hits" with downbeats
   *  or other rhythmic elements. */
  tremoloPhase: number

  // ── Panner (StereoPannerNode + LFO sweep) ─────────────────────────
  /** Per-effect bypass switch. */
  pannerEnabled: boolean
  /** Wet/dry mix.  0 = bypass (signal stays centered).  1 = full
   *  panning effect (signal sweeps L↔R within the spread range). */
  pannerMix: number
  /** Sweep LFO speed in Hz.  When 0, panner sits at center without
   *  movement (or at the spread midpoint, which is also center). */
  pannerSweepRate: number
  /** Rate-mode toggle.  "Hz" = use pannerSweepRate as-is.  "♪" =
   *  compute Hz from pannerSweepRateNote at the current effective
   *  BPM.  Mirrors the tremoloRateMode pattern.  Added in v0.3. */
  pannerSweepRateMode: "Hz" | "♪"
  /** Note fraction used when pannerSweepRateMode is "♪". */
  pannerSweepRateNote: string
  /** Spread to the LEFT, 0–1.  Controls how far the pan sweeps
   *  from center toward full left.  At 0 the carrier never goes
   *  left of center; at 1 it reaches full L (-1).  Decoupled from
   *  pannerSpreadR so the sweep can be asymmetric (e.g., pan only
   *  on the right side, or biased toward one channel). */
  pannerSpreadL: number
  /** Spread to the RIGHT, 0–1.  Mirror of pannerSpreadL — controls
   *  how far the carrier sweeps from center toward full right.
   *  Engine: low = -pannerSpreadL, high = +pannerSpreadR; midpoint
   *  = (R-L)/2; half-range = (R+L)/2. */
  pannerSpreadR: number
  /** Sweep waveform — same options as the ring-mod sweep. */
  pannerSweepWave: SweepWave

  // ── Delay (DelayNode + feedback gain + dry/wet) ──────────────────
  /** Per-effect bypass switch. */
  delayEnabled: boolean
  /** Delay time in seconds.  0–2 (DelayNode max).  Used directly
   *  when delayTimeMode is "ms"; ignored when mode is "♪" (the note
   *  fraction is converted to ms via the effective BPM at apply
   *  time). */
  delayTime: number
  /** Time-mode toggle.  "ms" = use delayTime as-is.  "♪" = compute
   *  ms from delayTimeNote at the current effective BPM (matches the
   *  slurmify side's note-mode pattern, ADR-0020). */
  delayTimeMode: "ms" | "♪"
  /** Note fraction string used when delayTimeMode is "♪".
   *  Same grammar as src/lib/note-mode.ts (e.g., "1/4", "1/8.",
   *  "1/16T"). */
  delayTimeNote: string
  /** Feedback gain.  0 = single repeat.  ~0.9 = self-oscillating
   *  drone.  Clamp ≤ 0.95 to avoid runaway. */
  delayFb: number
  /** Wet/dry mix.  0 = bypass.  1 = full wet (no dry signal). */
  delayMix: number

  // ── Phaser (4 allpass filters + LFO) ─────────────────────────────
  /** Per-effect bypass switch. */
  phaserEnabled: boolean
  /** LFO rate in Hz.  0.05 = slow sweep (~20 s).  5+ = throbbing. */
  phaseRate: number
  /** Rate-mode toggle.  "Hz" = use phaseRate as-is.  "♪" =
   *  compute Hz from phaseRateNote at the current effective BPM.
   *  Mirrors the tremoloRateMode pattern.  Added in v0.3. */
  phaseRateMode: "Hz" | "♪"
  /** Note fraction used when phaseRateMode is "♪". */
  phaseRateNote: string
  /** Phaser depth.  0 = bypass.  1 = full sweep + balanced wet/dry
   *  (matches v0.1.6's 0.5/0.5 mix when depth=1). */
  phaseDepth: number

  // ── Pitch shifter (pyrubberband on the Python side; Web Audio
  //     live preview pending v0.3.1 AudioWorklet phase-vocoder) ──
  /** Per-effect bypass switch. */
  pitchEnabled: boolean
  /** Coarse pitch shift in semitones.  -24 to +24 (two octaves
   *  each way).  Combined with pitchCents (cents/100) before the
   *  burn-fx payload is built — the Python schema accepts a single
   *  combined semitones float. */
  pitchSemitones: number
  /** Fine pitch shift in cents.  -100 to +100.  Pairs with
   *  pitchSemitones for sub-semitone precision (musicians-who-care
   *  use this for unison detune doubler effects at small mix). */
  pitchCents: number
  /** Wet/dry blend, 0–1.  Default 1.0 = fully pitched signal;
   *  intermediate values blend with the dry input for doubler
   *  effects (small semitones offset + mix=0.3 ≈ "thicker" sound). */
  pitchMix: number

  // ── Reverb (ConvolverNode with generated IR) ─────────────────────
  /** Per-effect bypass switch. */
  reverbEnabled: boolean
  /** Reverb tail length in seconds, 0.1–5.  Longer = bigger room.
   *  Changing this regenerates the impulse response (cheap — runs
   *  in ~10ms at 44.1kHz × 5s; throttled in useFxChain). */
  reverbSize: number
  /** Decay shape exponent, 1–6.  1 = linear fade.  Higher = faster
   *  initial decay (more "concrete bunker" early, longer "concert
   *  hall" tail). */
  reverbDecay: number
  /** Wet/dry mix.  0 = bypass.  1 = full wet. */
  reverbMix: number
}

export const defaultFxParams = (): FxParams => ({
  bypass:         false,

  distEnabled:    true,
  distGain:       0,
  distDrive:      0,
  distShape:      "soft",
  distTone:       0,

  ringEnabled:        true,
  ringFreq:           200,
  ringDepth:          0,
  ringSweepRate:      0,        // 0 = sweep off (static freq applies)
  ringSweepRateMode:  "Hz",
  ringSweepRateNote:  "1/4",
  ringSweepLow:       100,
  ringSweepHigh:      800,
  ringSweepWave:      "sine",

  tremoloEnabled:  true,
  tremoloRate:     4,
  tremoloRateMode: "Hz",
  tremoloRateNote: "1/4",
  tremoloDepth:    0,
  tremoloPhase:    0,

  pannerEnabled:        true,
  pannerMix:            0,
  pannerSweepRate:      0.5,
  pannerSweepRateMode:  "Hz",
  pannerSweepRateNote:  "1/4",
  pannerSpreadL:        1,
  pannerSpreadR:        1,
  pannerSweepWave:      "sine",

  delayEnabled:   true,
  delayTime:      0.3,
  delayTimeMode:  "ms",
  delayTimeNote:  "1/8",
  delayFb:        0.35,
  delayMix:       0,

  phaserEnabled:  true,
  phaseRate:      1.0,
  phaseRateMode:  "Hz",
  phaseRateNote:  "1/4",
  phaseDepth:     0,

  pitchEnabled:   true,
  pitchSemitones: 0,
  pitchCents:     0,
  pitchMix:       1.0,

  reverbEnabled:  true,
  reverbSize:     1.5,
  reverbDecay:    2.5,
  reverbMix:      0,
})

// ── Burn-job state ───────────────────────────────────────────────────
// Tracks an in-flight /burn-fx run.  Same shape as slurmStore's
// JobState — they're managed independently because the user can run
// a slurmify job and then a burn-fx job; the OUTPUT module shows
// whichever is most recent.

export interface FxBurnState {
  jobId:     string | null
  progress:  number          // 0-1
  desc:      string
  isRunning: boolean
  error:     string | null
  /** file_id of the burned-FX result.  Persists for the life of the
   *  session; the OUTPUT module's WaveformPlayer plays from
   *  /files/{burnedFileId} when this is set. */
  burnedFileId: string | null
}

const initialBurnState: FxBurnState = {
  jobId:        null,
  progress:     0,
  desc:         "",
  isRunning:    false,
  error:        null,
  burnedFileId: null,
}

interface FxStore extends FxBurnState {
  params: FxParams

  // ── Param actions ────────────────────────────────────────────────
  setParam:    <K extends keyof FxParams>(key: K, value: FxParams[K]) => void
  setParams:   (p: Partial<FxParams>) => void
  resetParams: () => void

  // ── Job lifecycle (used by useBurnFxJob) ─────────────────────────
  startBurn:  (jobId: string) => void
  updateBurn: (p: { progress: number; desc: string }) => void
  finishBurn: (burnedFileId: string | null, error: string | null) => void
  /** Forget the burned result — restores the OUTPUT player to the
   *  pre-burn slurm output.  Bound to a "revert to dry slurm" button. */
  clearBurn:  () => void
}

export const useFxStore = create<FxStore>()(
  persist(
    (set) => ({
      params: defaultFxParams(),
      ...initialBurnState,

      setParam: (key, value) =>
        set((s) => ({ params: { ...s.params, [key]: value } })),

      setParams: (p) =>
        set((s) => ({ params: { ...s.params, ...p } })),

      resetParams: () => set({ params: defaultFxParams() }),

      startBurn: (jobId) => set({
        jobId,
        progress:  0,
        desc:      "",
        isRunning: true,
        error:     null,
      }),

      updateBurn: ({ progress, desc }) => set({ progress, desc }),

      finishBurn: (burnedFileId, error) => set({
        burnedFileId,
        error,
        isRunning: false,
        progress:  burnedFileId ? 1 : 0,
      }),

      clearBurn: () => set(initialBurnState),
    }),
    {
      // BUMPED v6 → v7: added Hz ⇄ ♪ mode + note fields for the
      // three remaining rate params (ringSweepRate, pannerSweepRate,
      // phaseRate).  Stale v6 entries lack the new fields, which
      // would surface as `undefined` mode on first render —
      // KnobNoteToggle's mode toggle would render in a broken state
      // until the user clicked it.  See PLAN_FX_RACK_V0.3.md §3.2.
      //
      // v5 → v6 history: the single pannerSpread knob was reverted
      // to the asymmetric two-knob form (pannerSpreadL +
      // pannerSpreadR) so the user can clamp the sweep to one
      // side.  Stale v5 entries lacked the new fields and crashed
      // on first knob render.
      // BUMPED v7 → v8: added pitch shifter fields (pitchEnabled,
      // pitchSemitones, pitchCents, pitchMix) for v0.3 Phase 4.
      // Stale v7 entries lack these fields; if loaded without
      // bumping the version the pitch knobs would render undefined
      // values and the rack would behave erratically.  History
      // of prior bumps in this file: v5→v6 (asymmetric panner
      // spread), v6→v7 (beat-mode toggles on ring/panner/phaser
      // rate).
      name: "slurmify_fx_session_v8",
      // Only the user-meaningful preferences (knob positions) survive
      // reloads.  Burn-job state stays transient because burnedFileId
      // references a backend-side file that's gone after a sidecar
      // restart.
      partialize: (s) => ({ params: s.params }),
    },
  ),
)
