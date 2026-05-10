// ──────────────────────────────────────────────────────────────────────
// src/hooks/useFxChain.ts — Bind the Web Audio FX chain to a media element
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's `_fxSetup` + `_fxApply` from ui_assets.py,
// rewritten as a React hook + extended for v0.2.0 with two new effects
// (tremolo, reverb), distortion gain/shape/tone controls, per-effect
// bypass switches, and a master bypass.
//
// Topology (signal flow, left → right):
//
//   src
//    └─ distGain ─ distortion ─ distTone (high-shelf) ──── ring ──── trem ─┐
//                                                                          │
//   ┌──────────────────────────────────────────────────────────────────────┘
//   │
//   └─ delay ─ phaser ─ reverb ─ destination
//                                  └── analyser tap (off the dry phaser
//                                      output, fed into the VU meter)
//
// Each effect has a wet+dry mix.  Per-effect bypass is implemented via
// the `*Enabled` booleans in fxStore — when an effect is disabled, its
// mix collapses to dry passthrough (or, for distortion/ring/tremolo,
// the modulation amount is zeroed).  Master `bypass` zeroes EVERY
// effect simultaneously, restoring a fully-clean signal path.
//
// CRITICAL — ADR-0003 (refined for v0.2.0):
//
//   `AudioContext.createMediaElementSource(el)` is one-shot per
//   <audio> element.  Calling it twice on the same element throws.
//   But — crucially — when wavesurfer's underlying audio element is
//   RECREATED (e.g., when the WaveformPlayer remounts after a slurm
//   job finishes and isRunning toggles back to false), we DO need to
//   build a new chain bound to the new element.  Otherwise the new
//   element bypasses our chain entirely and effects appear silent.
//
//   The fix: track which audioEl the active chain is bound to
//   (FxNodes.audioEl).  When a different element arrives, tear down
//   the old AudioContext and build a fresh chain.  Closing the old
//   context releases its source-element binding so we don't leak.
//
//   This fixes the "FX inaudible during slurm playback" bug —
//   on first slurm completion the audioEl was a fresh element our
//   one-time `if (nodesRef.current) return` guard skipped.
//
// AudioContext autoplay-policy quirk:
//   Browsers create the context in 'suspended' state until a real
//   user gesture.  We attach a 'play' listener to the media element
//   so the context resumes the moment the user hits Play.
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from "react"
import { useFxStore, type FxParams, type DistShape, type SweepWave } from "@/stores/fxStore"
import { noteToMs } from "@/lib/note-mode"
import { useSlurmStore } from "@/stores/slurmStore"

// Augment Window with the legacy webkit-prefixed AudioContext for
// older WebKit-based runtimes.  Tauri's webview is recent enough that
// this isn't needed in practice, but the cost is one line + zero risk.
declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext
  }
}

interface FxNodes {
  ctx: AudioContext
  /** The audio element this chain is bound to.  When the React
   *  component passes a DIFFERENT element to useFxChain, we must
   *  tear down and rebuild — see the bug-fix block in the hook. */
  audioEl: HTMLMediaElement

  // ── Distortion stage ─────────────────────────────────────────────
  distGain: GainNode         // pre-WaveShaper input gain (dB-derived)
  dist:     WaveShaperNode   // selectable curve shape (soft/hard/fold/fuzz)
  distTone: BiquadFilterNode // post-distortion high-shelf tone tilt
  /** Dry/wet pair so per-effect bypass can collapse the chain stage to
   *  pure passthrough without touching the running oscillators. */
  distDry: GainNode
  distWet: GainNode
  distOut: GainNode

  // ── Ring mod ─────────────────────────────────────────────────────
  ringGain:   GainNode    // base passthrough (gain.value=1) + osc adds modulation
  ringOsc:    OscillatorNode
  ringOscAmp: GainNode    // depth multiplier on the oscillator output

  // ── Ring-mod frequency sweep (LFO that modulates ringOsc.frequency) ─
  /** Oscillator-based LFO source for sine/saw/square sweep waves.
   *  Connected to sweepRangeGain when wave is sine/saw/square. */
  sweepLFO:        OscillatorNode
  /** Looped white-noise buffer, low-pass filtered, used for the
   *  "noise" sweep wave (random wandering carrier).  Connected to
   *  sweepRangeGain when wave is "noise". */
  sweepNoise:      AudioBufferSourceNode
  sweepNoiseFilter: BiquadFilterNode
  /** Range scaler — maps the active source's -1..+1 output to
   *  ±(sweepHigh - sweepLow)/2 Hz around the midpoint. */
  sweepRangeGain:  GainNode
  /** Currently-active wave source.  Tracked so applyFxParams knows
   *  whether to disconnect/reconnect when the wave type changes
   *  (idempotent fast path skips reconnects when nothing changes). */
  activeSweepWave: SweepWave

  // ── Tremolo (amplitude modulation by a sine LFO) ─────────────────
  // Same osc → gain.gain pattern as the ring mod, but at LFO rates
  // (sub-20 Hz) so it reads as volume swell rather than ring metallic.
  // tremPhaseDelay sits between tremOscAmp and tremGain.gain — its
  // delayTime is set to (phase/360) × period to time-shift the LFO
  // signal, which is how we expose a 0–360° phase control without
  // having to stop/recreate the OscillatorNode on every change.
  tremGain:        GainNode
  tremOsc:         OscillatorNode
  tremOscAmp:      GainNode
  tremPhaseDelay:  DelayNode

  // ── Delay ────────────────────────────────────────────────────────
  delay:    DelayNode
  delayFb:  GainNode      // feedback loop gain
  delayDry: GainNode
  delayWet: GainNode
  delayOut: GainNode      // dry + wet merge point
  /** Tracks whether the feedback loop is currently CONNECTED.  We
   *  explicitly disconnect when feedback drops to zero (per
   *  ring-out bug: gain.value=0 is documented to fully attenuate but
   *  in practice some browsers have shown residual loop activity at
   *  the noise floor; disconnecting eliminates the path entirely). */
  delayFbConnected: boolean

  // ── Phaser ───────────────────────────────────────────────────────
  phaseAP:      BiquadFilterNode[]   // 4 allpass filters in series
  phaseLFO:     OscillatorNode
  phaseLFOGain: GainNode
  phaseDry:     GainNode
  phaseWet:     GainNode

  // ── Reverb (ConvolverNode + generated IR) ────────────────────────
  reverb:    ConvolverNode
  reverbDry: GainNode
  reverbWet: GainNode
  reverbOut: GainNode

  // ── Panner (StereoPannerNode + LFO sweep, mirrors ring-sweep wiring) ─
  pannerNode:        StereoPannerNode
  pannerDry:         GainNode
  pannerWet:         GainNode
  pannerOut:         GainNode
  /** Range scaler — gain.value is the half-range of the pan sweep
   *  ((high-low)/2).  Connected to pannerNode.pan so the LFO output
   *  is scaled into the user's [low, high] range and added to the
   *  base pan position. */
  pannerRangeGain:   GainNode
  pannerLFO:         OscillatorNode
  pannerNoise:       AudioBufferSourceNode
  pannerNoiseFilter: BiquadFilterNode
  /** Tracks the active panner-sweep wave so we only re-route on
   *  changes (mirrors the activeSweepWave pattern for ring). */
  activePannerWave:  SweepWave

  // ── Optional analyser tap ────────────────────────────────────────
  /** Tapped off the dry phaser output for VU visualisation. */
  analyser:     AnalyserNode
  analyserBuf:  Uint8Array
}

// ── Distortion curve generation ──────────────────────────────────────
// Each shape gets its own curve formula.  All produce values in [-1,
// +1] for input in [-1, +1], so signal level stays normalized.
//
//   soft  — tanh, smooth tube-like saturation (legacy default)
//   hard  — clipped to ±1 (drive-controlled threshold)
//   fold  — wavefolding via sin(k*x); higher drive → more folds
//   fuzz  — half-wave rectified asymmetric clipping
//
// At drive=0 every shape is the identity curve so the user can hear
// the BYPASSED signal flowing through the WaveShaper stage.

function buildDistortionCurve(drive: number, shape: DistShape): Float32Array {
  const n = 1024
  const curve = new Float32Array(n)
  const safe = Math.max(0, Math.min(1, drive))
  if (safe < 0.01) {
    for (let i = 0; i < n; i++) {
      curve[i] = (i / (n - 1)) * 2 - 1
    }
    return curve
  }

  switch (shape) {
    case "soft": {
      // tanh saturation, drive 0–1 maps to k 1–30.
      const k = 1 + safe * 29
      const tanhK = Math.tanh(k)
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * 2 - 1
        curve[i] = Math.tanh(k * x) / tanhK
      }
      break
    }
    case "hard": {
      // Hard-clip to threshold = 1 - 0.9*drive.  Higher drive →
      // lower threshold → more aggressive clipping.
      const t = 1 - 0.9 * safe
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * 2 - 1
        if      (x >  t) curve[i] =  1
        else if (x < -t) curve[i] = -1
        else             curve[i] = x / t
      }
      break
    }
    case "fold": {
      // Wavefolder — sin(k*x) wraps around as drive increases.
      // k 1–8 gives a useful range; beyond 8 it's noise.
      const k = 1 + safe * 7
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * 2 - 1
        curve[i] = Math.sin(k * x) / Math.sin(k)
      }
      break
    }
    case "fuzz": {
      // Asymmetric half-wave-rectified clipping — transistor fuzz feel.
      // Negative half tanh-saturates softly; positive half hard-clips.
      const k = 1 + safe * 19
      const tanhK = Math.tanh(k)
      const t = 1 - 0.7 * safe
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * 2 - 1
        if (x >= 0) {
          curve[i] = x > t ? 1 : x / t
        } else {
          curve[i] = Math.tanh(k * x) / tanhK
        }
      }
      break
    }
  }
  return curve
}

// ── Reverb impulse response generation ───────────────────────────────
// Generate a stereo impulse response: white noise enveloped by an
// exponential decay.  Cheap (a few ms even at 5 seconds × 48 kHz) and
// produces a plausible "room" reverb without any external IR files.
// Larger size = bigger room; higher decay exponent = faster attack.
function buildReverbIR(
  ctx: AudioContext,
  sizeSec: number,
  decayExp: number,
): AudioBuffer {
  const sampleRate = ctx.sampleRate
  const length = Math.max(1, Math.floor(sampleRate * Math.max(0.05, Math.min(5, sizeSec))))
  const ir = ctx.createBuffer(2, length, sampleRate)
  const e = Math.max(1, Math.min(6, decayExp))
  for (let ch = 0; ch < 2; ch++) {
    const data = ir.getChannelData(ch)
    for (let i = 0; i < length; i++) {
      const t = i / length
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - t, e)
    }
  }
  return ir
}

// ── Param application ────────────────────────────────────────────────
// Per-knob-twist hot path.  For most params this is a single
// AudioParam write; for the distortion curve and reverb IR we cache
// the previous values and only rebuild when they change.

interface ApplyState {
  prevDistDrive: number
  prevDistShape: DistShape
  prevReverbSize: number
  prevReverbDecay: number
  /** Tracks the previously-applied sweep wave so we only re-route
   *  the sweep-source connections when the wave actually changes. */
  prevSweepWave: SweepWave
  /** Same idea but for the panner's sweep wave routing. */
  prevPannerWave: SweepWave
}

// ── Effective BPM resolution for FX note-mode ────────────────────────
// Mirrors the priority used by useEffectiveBpm in the slurm side:
//   1. explicit user override (slurmStore.params.bpm_override)
//   2. librosa auto-detection (slurmStore.analysis.bpm)
//   3. 120 default
// We resolve here rather than via the hook because applyFxParams
// runs OUTSIDE React's render cycle (it's called from a
// non-component effect dependency).  Reading slurmStore.getState()
// is the documented Zustand escape hatch for this pattern.
function resolveEffectiveBpm(): number {
  const slurm = useSlurmStore.getState()
  const override = slurm.params.bpm_override
  if (override !== null && override > 0) return override
  const detected = slurm.analysis?.bpm ?? null
  if (detected !== null && detected > 0) return detected
  return 120
}

function applyFxParams(n: FxNodes, p: FxParams, st: ApplyState): void {
  const masterOff = p.bypass

  // ── Distortion ────────────────────────────────────────────────────
  // distGain is in dB; convert to linear via 10^(dB/20).
  const distOn = !masterOff && p.distEnabled
  n.distGain.gain.value = distOn ? Math.pow(10, p.distGain / 20) : 1

  // Curve rebuild only when drive OR shape changes.  Saves the
  // Float32Array allocation on every other knob twist.
  if (p.distDrive !== st.prevDistDrive || p.distShape !== st.prevDistShape) {
    n.dist.curve = buildDistortionCurve(distOn ? p.distDrive : 0, p.distShape)
    st.prevDistDrive = p.distDrive
    st.prevDistShape = p.distShape
  } else if (!distOn && st.prevDistDrive > 0) {
    // Bypass forces drive=0 effectively; mark the cached drive as 0
    // so a subsequent re-enable triggers a curve rebuild.
    n.dist.curve = buildDistortionCurve(0, p.distShape)
    st.prevDistDrive = 0
  }

  // Tone filter — high-shelf at 2 kHz, gain in dB driven by distTone
  // (-1 dark = -12 dB, +1 bright = +12 dB).  Bypass leaves it flat (0 dB).
  n.distTone.gain.value = distOn ? p.distTone * 12 : 0

  // ── Ring mod ──────────────────────────────────────────────────────
  // Bypass forces depth = 0 (oscillator keeps running, but its gain
  // contribution is zero — no audible modulation).
  // Carrier frequency is either the static ringFreq (sweep off) or
  // the midpoint of the sweep range (sweep on).
  const ringOn = !masterOff && p.ringEnabled
  const sweepActive = ringOn && p.ringSweepRate > 0
  if (sweepActive) {
    const lo = Math.max(0, Math.min(p.ringSweepLow, p.ringSweepHigh))
    const hi = Math.max(p.ringSweepLow, p.ringSweepHigh)
    const mid   = (lo + hi) / 2
    const range = (hi - lo) / 2
    n.ringOsc.frequency.value = mid
    n.sweepRangeGain.gain.value = range
    // For sine/saw/square: feed the LFO at sweep rate.
    n.sweepLFO.frequency.value = p.ringSweepRate
    // For noise: scale the noise-filter cutoff to the rate so a
    // higher rate = faster wandering.  Cutoff = rate × 4 Hz keeps
    // the noise SLOW at low rates (musical wobble) and frenetic
    // at high rates.
    n.sweepNoiseFilter.frequency.value = Math.max(0.5, p.ringSweepRate * 4)
  } else {
    n.ringOsc.frequency.value = p.ringFreq
    n.sweepRangeGain.gain.value = 0
  }

  // Sweep-wave routing — disconnect the old source and connect the new
  // one ONLY when the wave actually changed (avoids audible clicks
  // from re-routing on every knob twist).
  if (p.ringSweepWave !== st.prevSweepWave) {
    try { n.sweepLFO.disconnect() } catch { /* not connected */ }
    try { n.sweepNoiseFilter.disconnect() } catch { /* not connected */ }
    if (p.ringSweepWave === "noise") {
      n.sweepNoiseFilter.connect(n.sweepRangeGain)
    } else {
      // OscillatorNode types: "sine" | "sawtooth" | "square" |
      // "triangle".  Map our "saw" → "sawtooth"; everything else
      // matches one-for-one.
      n.sweepLFO.type = p.ringSweepWave === "saw" ? "sawtooth" : p.ringSweepWave
      n.sweepLFO.connect(n.sweepRangeGain)
    }
    st.prevSweepWave = p.ringSweepWave
  }

  n.ringOscAmp.gain.value   = ringOn ? p.ringDepth : 0

  // ── Tremolo ───────────────────────────────────────────────────────
  // Same pattern as ring mod but at sub-audio LFO rates.  Bypass
  // forces depth=0 so the gain stays at its base 1.0.  Rate can be
  // either Hz (used directly) or ♪ (note value at the current
  // effective BPM, converted via 1000 / noteToMs).
  let tremRate = p.tremoloRate
  if (p.tremoloRateMode === "♪") {
    const bpm = resolveEffectiveBpm()
    const ms  = noteToMs(p.tremoloRateNote, bpm)
    if (ms > 0) tremRate = 1000 / ms
  }
  n.tremOsc.frequency.value = Math.max(0.01, tremRate)
  n.tremOscAmp.gain.value   = !masterOff && p.tremoloEnabled ? p.tremoloDepth : 0
  // Phase offset — delay the LFO output by (phase/360) × period.
  // Clamped to the DelayNode's max (20 s).  When phase=0 or rate=0
  // we set delayTime=0 (passthrough).
  const tremPeriodSec = tremRate > 0 ? 1 / tremRate : 0
  const tremPhaseSec  = ((p.tremoloPhase % 360) / 360) * tremPeriodSec
  n.tremPhaseDelay.delayTime.value = Math.min(20, Math.max(0, tremPhaseSec))

  // ── Delay ─────────────────────────────────────────────────────────
  // Clamp feedback below the runaway threshold.  Bypass collapses
  // mix to 0 (full dry).  Time can be either ms (delayTime in
  // seconds, used directly) or ♪ (delayTimeNote converted via the
  // current effective BPM — same priority as the slurm side:
  // bpm_override → analysis.bpm → 120 default).
  const delayOn = !masterOff && p.delayEnabled
  let delaySec = Math.min(Math.max(p.delayTime, 0), 2)
  if (p.delayTimeMode === "♪") {
    const bpm = resolveEffectiveBpm()
    const ms  = noteToMs(p.delayTimeNote, bpm)
    if (ms > 0) {
      // noteToMs returns milliseconds; convert to seconds + clamp
      // to the DelayNode's max (2.0s).
      delaySec = Math.min(Math.max(ms / 1000, 0), 2)
    }
  }
  n.delay.delayTime.value = delaySec

  // Feedback wiring — explicit disconnect when value is zero.  The
  // GainNode's gain.value=0 SHOULD fully attenuate the loop, but
  // we observed residual feedback at user-reported "infinity"
  // levels in some sessions (likely from denormalized samples
  // accumulating in the loop).  Disconnecting the path entirely
  // eliminates any chance of residual activity.
  const wantFbConnected = delayOn && p.delayFb > 0.001
  if (wantFbConnected !== n.delayFbConnected) {
    if (wantFbConnected) {
      n.delayFb.connect(n.delay)
    } else {
      try { n.delayFb.disconnect(n.delay) } catch { /* not connected */ }
    }
    n.delayFbConnected = wantFbConnected
  }
  n.delayFb.gain.value  = wantFbConnected ? Math.min(Math.max(p.delayFb, 0), 0.95) : 0
  n.delayDry.gain.value = delayOn ? 1 - p.delayMix : 1
  n.delayWet.gain.value = delayOn ? p.delayMix     : 0

  // ── Phaser ────────────────────────────────────────────────────────
  // Depth controls both LFO amplitude AND wet/dry mix in lockstep.
  const phaseOn = !masterOff && p.phaserEnabled
  n.phaseLFO.frequency.value = p.phaseRate
  n.phaseLFOGain.gain.value  = phaseOn ? 500 * p.phaseDepth : 0
  n.phaseDry.gain.value      = phaseOn ? 1 - p.phaseDepth * 0.5 : 1
  n.phaseWet.gain.value      = phaseOn ? p.phaseDepth * 0.5     : 0

  // ── Reverb ────────────────────────────────────────────────────────
  const reverbOn = !masterOff && p.reverbEnabled
  // Regenerate the IR only when size or decay changes.  Each
  // regeneration is ~5–20ms; ConvolverNode swaps its buffer atomically
  // so there's no audio dropout.
  if (p.reverbSize !== st.prevReverbSize || p.reverbDecay !== st.prevReverbDecay) {
    n.reverb.buffer = buildReverbIR(n.ctx, p.reverbSize, p.reverbDecay)
    st.prevReverbSize  = p.reverbSize
    st.prevReverbDecay = p.reverbDecay
  }
  n.reverbDry.gain.value = reverbOn ? 1 - p.reverbMix : 1
  n.reverbWet.gain.value = reverbOn ? p.reverbMix     : 0

  // ── Panner ────────────────────────────────────────────────────────
  // StereoPannerNode whose .pan AudioParam is modulated by the same
  // LFO/noise pattern as the ring sweep, scaled into the user's
  // [low, high] range and offset to the midpoint.
  const pannerOn = !masterOff && p.pannerEnabled
  const pannerSweepActive = pannerOn && p.pannerSweepRate > 0
  // Asymmetric spread: the sweep range is [-L, +R].  Midpoint
  // (where the pan parks when sweep is off) = (R - L) / 2.
  // Half-range (the LFO scaling) = (R + L) / 2.  When L=R=1 this
  // collapses to the symmetric L↔R sweep with midpoint 0; when
  // L=0,R=1 it's a "right-only" sweep parked at +0.5 with half-
  // range 0.5; etc.
  const sL = Math.max(0, Math.min(1, p.pannerSpreadL))
  const sR = Math.max(0, Math.min(1, p.pannerSpreadR))
  const pannerMid       = (sR - sL) / 2
  const pannerHalfRange = (sR + sL) / 2
  if (pannerSweepActive) {
    n.pannerNode.pan.value       = pannerMid
    n.pannerRangeGain.gain.value = pannerHalfRange
    n.pannerLFO.frequency.value  = p.pannerSweepRate
    n.pannerNoiseFilter.frequency.value = Math.max(0.5, p.pannerSweepRate * 4)
  } else {
    // Sweep off — pan parks at the midpoint (still respects
    // asymmetric L/R weighting; L=1,R=0 parks at -0.5).
    n.pannerNode.pan.value       = pannerOn ? pannerMid : 0
    n.pannerRangeGain.gain.value = 0
  }
  // Sweep-wave routing — same disconnect/reconnect dance as ring.
  if (p.pannerSweepWave !== st.prevPannerWave) {
    try { n.pannerLFO.disconnect() }         catch { /* not connected */ }
    try { n.pannerNoiseFilter.disconnect() } catch { /* not connected */ }
    if (p.pannerSweepWave === "noise") {
      n.pannerNoiseFilter.connect(n.pannerRangeGain)
    } else {
      n.pannerLFO.type = p.pannerSweepWave === "saw" ? "sawtooth" : p.pannerSweepWave
      n.pannerLFO.connect(n.pannerRangeGain)
    }
    st.prevPannerWave = p.pannerSweepWave
  }
  // Wet/dry mix — when mix=0 (or panner bypassed), dry-only path
  // bypasses the StereoPannerNode entirely so the user hears the
  // reverb output unchanged.
  n.pannerDry.gain.value = pannerOn ? 1 - p.pannerMix : 1
  n.pannerWet.gain.value = pannerOn ? p.pannerMix     : 0
}

// ── buildFxChain — full constructor for the audio graph ──────────────

function buildFxChain(audioEl: HTMLMediaElement, initial: FxParams): FxNodes | null {
  const Ctx = window.AudioContext ?? window.webkitAudioContext
  if (!Ctx) {
    // eslint-disable-next-line no-console
    console.warn("[fx] AudioContext not available — skipping FX chain")
    return null
  }
  const ctx = new Ctx()

  let src: MediaElementAudioSourceNode
  try {
    src = ctx.createMediaElementSource(audioEl)
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error("[fx] createMediaElementSource failed:", e)
    void ctx.close()
    return null
  }

  // ── Distortion stage (gain → shaper → tone, with wet/dry pair) ──
  const distGain = ctx.createGain()
  distGain.gain.value = Math.pow(10, initial.distGain / 20)
  const dist = ctx.createWaveShaper()
  dist.curve = buildDistortionCurve(initial.distDrive, initial.distShape)
  dist.oversample = "2x"
  const distTone = ctx.createBiquadFilter()
  distTone.type = "highshelf"
  distTone.frequency.value = 2000
  distTone.gain.value = initial.distTone * 12
  const distDry = ctx.createGain()
  const distWet = ctx.createGain()
  const distOut = ctx.createGain()
  distDry.gain.value = 0   // we don't actually use a dry-bypass for this
  distWet.gain.value = 1   // stage; bypass is implemented by setting
                           // distGain=1 + drive=0 + distTone gain=0.
  distDry.connect(distOut)
  distWet.connect(distOut)

  // ── Ring mod (with frequency sweep LFO) ──────────────────────────
  // The ring carrier (ringOsc) is modulated by an LFO chain that's
  // routed through sweepRangeGain into ringOsc.frequency.  Two
  // possible LFO sources — sweepLFO (sine/saw/square) and sweepNoise
  // (band-limited random) — only one is connected to sweepRangeGain
  // at a time, keyed off the active wave type.
  const ringGain = ctx.createGain()
  ringGain.gain.value = 1.0
  const ringOsc = ctx.createOscillator()
  ringOsc.type = "sine"
  ringOsc.frequency.value = initial.ringFreq
  const ringOscAmp = ctx.createGain()
  ringOscAmp.gain.value = initial.ringEnabled ? initial.ringDepth : 0
  ringOsc.connect(ringOscAmp)
  ringOscAmp.connect(ringGain.gain)
  ringOsc.start()

  // Sweep range scaler — gain.value is the sweep amplitude in Hz,
  // set in applyFxParams to (high-low)/2 when the sweep is active.
  // Connected directly to ringOsc.frequency so the modulation rides
  // on top of the base value.
  const sweepRangeGain = ctx.createGain()
  sweepRangeGain.gain.value = 0
  sweepRangeGain.connect(ringOsc.frequency)

  // Oscillator-based sweep source for sine/saw/square.  Started
  // immediately and left running for the chain's lifetime; gain is
  // controlled by sweepRangeGain, and re-routing happens on wave
  // change in applyFxParams.
  const sweepLFO = ctx.createOscillator()
  sweepLFO.type = (initial.ringSweepWave === "saw"
    ? "sawtooth"
    : initial.ringSweepWave === "noise"
      ? "sine"      // placeholder; noise uses sweepNoise instead
      : initial.ringSweepWave) as OscillatorType
  sweepLFO.frequency.value = Math.max(0.01, initial.ringSweepRate)
  sweepLFO.start()

  // Noise sweep source — a 2-second white-noise buffer played in a
  // loop, low-pass filtered to the sweep rate × 4 Hz so the
  // wandering character scales with the rate knob.  AudioBufferSource
  // can't be re-started after stop(), so we never call stop() —
  // .loop = true keeps it running indefinitely; gain control sits
  // downstream at sweepRangeGain.
  const sweepNoiseBuffer = ctx.createBuffer(
    1,
    Math.floor(ctx.sampleRate * 2),
    ctx.sampleRate,
  )
  {
    const data = sweepNoiseBuffer.getChannelData(0)
    for (let i = 0; i < data.length; i++) {
      data[i] = Math.random() * 2 - 1
    }
  }
  const sweepNoise = ctx.createBufferSource()
  sweepNoise.buffer = sweepNoiseBuffer
  sweepNoise.loop = true
  const sweepNoiseFilter = ctx.createBiquadFilter()
  sweepNoiseFilter.type = "lowpass"
  sweepNoiseFilter.frequency.value = Math.max(0.5, initial.ringSweepRate * 4)
  sweepNoiseFilter.Q.value = 0.7
  sweepNoise.connect(sweepNoiseFilter)
  sweepNoise.start()

  // Initial routing — connect whichever source matches the initial
  // wave type.  applyFxParams will manage subsequent re-routes.
  if (initial.ringSweepWave === "noise") {
    sweepNoiseFilter.connect(sweepRangeGain)
  } else {
    sweepLFO.connect(sweepRangeGain)
  }

  // ── Tremolo (amplitude modulation by a sine LFO) ─────────────────
  // tremOsc → tremOscAmp → tremPhaseDelay → tremGain.gain
  // The phase delay is the new piece — at 0 it's a passthrough, at
  // higher values it shifts the LFO signal forward in time, which
  // is equivalent to a phase offset of the modulation.  Max delay
  // is 20 s, enough to support a full 360° phase at the slowest
  // rate (0.05 Hz → 20 s per period).
  const tremGain = ctx.createGain()
  tremGain.gain.value = 1.0
  const tremOsc = ctx.createOscillator()
  tremOsc.type = "sine"
  tremOsc.frequency.value = initial.tremoloRate
  const tremOscAmp = ctx.createGain()
  tremOscAmp.gain.value = initial.tremoloEnabled ? initial.tremoloDepth : 0
  const tremPhaseDelay = ctx.createDelay(20.0)
  tremPhaseDelay.delayTime.value = 0
  tremOsc.connect(tremOscAmp)
  tremOscAmp.connect(tremPhaseDelay)
  tremPhaseDelay.connect(tremGain.gain)
  tremOsc.start()

  // ── Delay (feedback loop + dry/wet) ──────────────────────────────
  const delay    = ctx.createDelay(2.0)
  const delayFb  = ctx.createGain()
  const delayDry = ctx.createGain()
  const delayWet = ctx.createGain()
  const delayOut = ctx.createGain()
  delay.delayTime.value = initial.delayTime
  const initialFb = initial.delayEnabled ? initial.delayFb : 0
  delayFb.gain.value    = initialFb
  delayDry.gain.value   = 1
  delayWet.gain.value   = 0
  delay.connect(delayFb)
  // Only wire the feedback loop CLOSED when the initial feedback
  // value is non-zero.  applyFxParams will manage the connection
  // dynamically as the user twists the knob.
  const initialFbConnected = initialFb > 0.001
  if (initialFbConnected) {
    delayFb.connect(delay)
  }
  delay.connect(delayWet)
  delayDry.connect(delayOut)
  delayWet.connect(delayOut)

  // ── Phaser (4 allpass filters with LFO-modulated frequency) ──────
  const phaseAP: BiquadFilterNode[] = []
  for (let i = 0; i < 4; i++) {
    const ap = ctx.createBiquadFilter()
    ap.type = "allpass"
    ap.frequency.value = 200 * Math.pow(4, i / 3.0)
    ap.Q.value = 0.5
    phaseAP.push(ap)
  }
  const phaseLFO     = ctx.createOscillator()
  const phaseLFOGain = ctx.createGain()
  phaseLFO.frequency.value = initial.phaseRate
  phaseLFOGain.gain.value  = 0
  phaseLFO.connect(phaseLFOGain)
  phaseAP.forEach((ap) => phaseLFOGain.connect(ap.frequency))
  phaseLFO.start()
  for (let j = 1; j < phaseAP.length; j++) {
    phaseAP[j - 1].connect(phaseAP[j])
  }
  const phaseDry = ctx.createGain()
  const phaseWet = ctx.createGain()
  phaseDry.gain.value = 1
  phaseWet.gain.value = 0

  // ── Reverb (ConvolverNode with generated IR + dry/wet) ───────────
  const reverb    = ctx.createConvolver()
  reverb.buffer   = buildReverbIR(ctx, initial.reverbSize, initial.reverbDecay)
  const reverbDry = ctx.createGain()
  const reverbWet = ctx.createGain()
  const reverbOut = ctx.createGain()
  reverbDry.gain.value = 1
  reverbWet.gain.value = 0
  reverbDry.connect(reverbOut)
  reverb.connect(reverbWet)
  reverbWet.connect(reverbOut)

  // ── Panner (post-reverb, pre-destination) ────────────────────────
  // StereoPannerNode whose .pan AudioParam is modulated by an LFO
  // chain identical in shape to the ring-mod sweep.  Wet/dry pair
  // lets the user blend the auto-panned signal with a centered
  // (un-panned) copy.
  const pannerNode      = ctx.createStereoPanner()
  pannerNode.pan.value  = 0
  const pannerDry       = ctx.createGain()
  const pannerWet       = ctx.createGain()
  const pannerOut       = ctx.createGain()
  pannerDry.gain.value  = 1
  pannerWet.gain.value  = 0

  // Sweep range scaler — drives pannerNode.pan modulation.
  const pannerRangeGain = ctx.createGain()
  pannerRangeGain.gain.value = 0
  pannerRangeGain.connect(pannerNode.pan)

  // LFO osc for sine/saw/square sweep waves.
  const pannerLFO = ctx.createOscillator()
  pannerLFO.type =
    initial.pannerSweepWave === "saw"   ? "sawtooth"
    : initial.pannerSweepWave === "noise" ? "sine"  // noise uses pannerNoise instead
    : initial.pannerSweepWave
  pannerLFO.frequency.value = Math.max(0.01, initial.pannerSweepRate)
  pannerLFO.start()

  // Noise sweep source — 2-second white-noise loop, low-pass
  // filtered to (rate × 4) Hz so wandering character scales with
  // the rate knob.  Same pattern as the ring-mod sweepNoise.
  const pannerNoiseBuffer = ctx.createBuffer(
    1,
    Math.floor(ctx.sampleRate * 2),
    ctx.sampleRate,
  )
  {
    const data = pannerNoiseBuffer.getChannelData(0)
    for (let i = 0; i < data.length; i++) {
      data[i] = Math.random() * 2 - 1
    }
  }
  const pannerNoise = ctx.createBufferSource()
  pannerNoise.buffer = pannerNoiseBuffer
  pannerNoise.loop = true
  const pannerNoiseFilter = ctx.createBiquadFilter()
  pannerNoiseFilter.type = "lowpass"
  pannerNoiseFilter.frequency.value = Math.max(0.5, initial.pannerSweepRate * 4)
  pannerNoiseFilter.Q.value = 0.7
  pannerNoise.connect(pannerNoiseFilter)
  pannerNoise.start()

  // Initial wave routing.
  if (initial.pannerSweepWave === "noise") {
    pannerNoiseFilter.connect(pannerRangeGain)
  } else {
    pannerLFO.connect(pannerRangeGain)
  }

  pannerDry.connect(pannerOut)
  pannerNode.connect(pannerWet)
  pannerWet.connect(pannerOut)

  // ── Wire the full chain ──────────────────────────────────────────
  // Each effect's wet/dry pair lives at its boundary so per-effect
  // bypass can mute the wet side without disrupting downstream.
  src.connect(distGain)
  distGain.connect(dist)
  dist.connect(distTone)
  distTone.connect(distWet)   // distWet → distOut
  // (distDry path unused for distortion — the bypass is parametric)

  distOut.connect(ringGain)
  ringGain.connect(tremGain)

  // Tremolo output splits into delay's dry + wet inputs.
  tremGain.connect(delayDry)
  tremGain.connect(delay)

  // Delay output splits into phaser's dry + first allpass.
  delayOut.connect(phaseDry)
  delayOut.connect(phaseAP[0])

  // Phaser's last allpass to its wet gain; both phaser dry/wet feed
  // into the reverb's dry side AND the convolver's input.
  phaseAP[phaseAP.length - 1].connect(phaseWet)
  phaseDry.connect(reverbDry)
  phaseWet.connect(reverbDry)
  phaseDry.connect(reverb)
  phaseWet.connect(reverb)

  // Reverb output flows into the panner stage (dry + wet split),
  // and the panner stage merges into the destination.  When the
  // panner mix is 0 the dry path sends the reverb output to
  // destination unchanged; when mix > 0 the wet path mixes in the
  // pan-modulated copy.
  reverbOut.connect(pannerDry)
  reverbOut.connect(pannerNode)
  pannerOut.connect(ctx.destination)

  // ── Analyser tap (off the dry phaser output) ─────────────────────
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 256
  analyser.smoothingTimeConstant = 0.7
  phaseDry.connect(analyser)
  const analyserBuf = new Uint8Array(analyser.frequencyBinCount)

  // ── Resume on play ───────────────────────────────────────────────
  const onPlay = () => {
    if (ctx.state === "suspended") {
      ctx.resume().catch((e) => {
        // eslint-disable-next-line no-console
        console.warn("[fx] AudioContext.resume() rejected:", e)
      })
    }
  }
  audioEl.addEventListener("play", onPlay)
  if (ctx.state === "suspended") {
    void ctx.resume().catch(() => {/* silently ignored */})
  }

  // eslint-disable-next-line no-console
  console.log(`[fx] chain ready, sr=${ctx.sampleRate}`)

  return {
    ctx, audioEl,
    distGain, dist, distTone, distDry, distWet, distOut,
    ringGain, ringOsc, ringOscAmp,
    sweepLFO, sweepNoise, sweepNoiseFilter, sweepRangeGain,
    activeSweepWave: initial.ringSweepWave,
    tremGain, tremOsc, tremOscAmp, tremPhaseDelay,
    delay, delayFb, delayDry, delayWet, delayOut,
    delayFbConnected: initialFbConnected,
    phaseAP, phaseLFO, phaseLFOGain, phaseDry, phaseWet,
    reverb, reverbDry, reverbWet, reverbOut,
    pannerNode, pannerDry, pannerWet, pannerOut,
    pannerRangeGain, pannerLFO, pannerNoise, pannerNoiseFilter,
    activePannerWave: initial.pannerSweepWave,
    analyser, analyserBuf,
  }
}

export interface UseFxChainResult {
  ready:    boolean
  analyser: AnalyserNode | null
  analyserBuf: Uint8Array | null
}

export function useFxChain(audioEl: HTMLMediaElement | null): UseFxChainResult {
  // The chain is held in a ref because rebuilding it on every render
  // would re-run createMediaElementSource and crash.  We track the
  // bound audioEl INSIDE the chain so we can detect a fresh element
  // and rebuild only then (per the bug-fix block at the top of this
  // file).
  const nodesRef = useRef<FxNodes | null>(null)

  // Cached previous values for the fields that drive expensive
  // rebuilds (curve, IR).  Lives outside the chain ref so it survives
  // a chain teardown + rebuild.
  const applyStateRef = useRef<ApplyState>({
    prevDistDrive:   -1,
    prevDistShape:   "soft",
    prevReverbSize:  -1,
    prevReverbDecay: -1,
    prevSweepWave:   "sine",
    prevPannerWave:  "sine",
  })

  const params = useFxStore((s) => s.params)

  // ── Bind / rebind on element change ──────────────────────────────
  useEffect(() => {
    if (!audioEl) return

    // Same element we're already bound to → idempotent fast path.
    if (nodesRef.current?.audioEl === audioEl) return

    // Different element (or first build) — tear down previous chain.
    // Closing the AudioContext releases the createMediaElementSource
    // binding on the OLD element so the OS-level audio path is freed
    // for it.  The new element gets a fresh source node below.
    if (nodesRef.current) {
      try {
        void nodesRef.current.ctx.close()
      } catch {
        // ignore — close() throws if already closed
      }
      nodesRef.current = null
      // Reset the cached state so the new chain rebuilds curve + IR
      // on first param-apply pass.
      applyStateRef.current = {
        prevDistDrive:   -1,
        prevDistShape:   "soft",
        prevReverbSize:  -1,
        prevReverbDecay: -1,
        prevSweepWave:   "sine",
        prevPannerWave:  "sine",
      }
    }

    const nodes = buildFxChain(audioEl, useFxStore.getState().params)
    if (nodes) {
      nodesRef.current = nodes
      // Apply current params immediately so the freshly-built chain
      // honors any non-default values (e.g., user has saved presets
      // with FX knobs at non-zero positions).
      applyFxParams(nodes, useFxStore.getState().params, applyStateRef.current)
    }
  }, [audioEl])

  // ── Re-apply params on every store update ────────────────────────
  useEffect(() => {
    if (!nodesRef.current) return
    applyFxParams(nodesRef.current, params, applyStateRef.current)
  }, [params])

  return {
    ready:       nodesRef.current !== null,
    analyser:    nodesRef.current?.analyser    ?? null,
    analyserBuf: nodesRef.current?.analyserBuf ?? null,
  }
}
