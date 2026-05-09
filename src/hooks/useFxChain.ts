// ──────────────────────────────────────────────────────────────────────
// src/hooks/useFxChain.ts — Bind the Web Audio FX chain to a media element
// ──────────────────────────────────────────────────────────────────────
//
// Direct port of v0.1.6's `_fxSetup` + `_fxApply` from ui_assets.py,
// rewritten as a React hook.  The DSP topology is unchanged:
//
//   src → distortion → ringMod → delay → phaser → destination
//                                                   └── analyser tap
//
// CRITICAL — ADR-0003 carries forward to v0.2.0:
//
//   `AudioContext.createMediaElementSource(el)` is one-shot per
//   <audio> element.  Calling it twice on the same element throws
//   "InvalidStateError: Failed to execute 'createMediaElementSource'
//   on 'AudioContext': HTMLMediaElement already connected to a
//   different MediaElementSourceNode".
//
//   Closing the AudioContext does NOT release the binding.  The
//   only escape is to point wavesurfer at a new <audio> element,
//   which would require remounting the WaveformPlayer — and that
//   destroys playback state, focus, and wavesurfer's internal
//   render cache.
//
// Solution (same as v0.1.6's `if (_fxCtx) return` guard): the hook
// is idempotent.  It binds the chain on first invocation with a real
// HTMLMediaElement and ignores all subsequent ones.  When the
// WaveformPlayer's URL changes, wavesurfer reuses the same audio
// element — our binding survives.
//
// The FX params come from useFxStore; an effect re-applies them
// whenever the store updates.  Re-applying is cheap (8 AudioParam
// writes); doing it on every mutation keeps the live preview
// instantly reactive to knob twists.
//
// AudioContext autoplay-policy quirk:
//   Browsers create the context in 'suspended' state until a real
//   user gesture.  We attach a 'play' listener to the media element
//   so the context resumes the moment the user hits Play (which IS
//   a user gesture — passes the autoplay heuristic).
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useRef } from "react"
import { useFxStore, type FxParams } from "@/stores/fxStore"

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

  // ── Distortion ────────────────────────────────────────────────────
  dist: WaveShaperNode

  // ── Ring mod ──────────────────────────────────────────────────────
  ringGain:   GainNode    // base passthrough (gain.value=1) + osc adds modulation
  ringOsc:    OscillatorNode
  ringOscAmp: GainNode    // depth multiplier on the oscillator output

  // ── Delay ─────────────────────────────────────────────────────────
  delay:    DelayNode
  delayFb:  GainNode      // feedback loop gain
  delayDry: GainNode
  delayWet: GainNode
  delayOut: GainNode      // dry + wet merge point

  // ── Phaser ────────────────────────────────────────────────────────
  phaseAP:      BiquadFilterNode[]   // 4 allpass filters in series
  phaseLFO:     OscillatorNode
  phaseLFOGain: GainNode
  phaseDry:     GainNode
  phaseWet:     GainNode

  // ── Optional analyser tap ────────────────────────────────────────
  /** Tapped off the dry phase output for VU/halo visualisation. */
  analyser:     AnalyserNode
  /** Pre-allocated buffer for getByteTimeDomainData() — caller reuses
   *  it on every animation frame to avoid GC pressure. */
  analyserBuf:  Uint8Array
}

/** Build the tanh-shaped distortion curve.  Direct port of `_fxCurve`. */
function buildDistortionCurve(drive: number): Float32Array {
  const n = 1024
  const curve = new Float32Array(n)
  const k = drive < 0.01 ? 0 : 1 + drive * 29
  if (k === 0) {
    // Pure passthrough — preserves sample magnitudes exactly.
    for (let i = 0; i < n; i++) {
      curve[i] = (i / (n - 1)) * 2 - 1
    }
  } else {
    const tanhK = Math.tanh(k)
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1)) * 2 - 1
      curve[i] = Math.tanh(k * x) / tanhK
    }
  }
  return curve
}

/** Apply current params to the running FX nodes.  Cheap — 8 AudioParam
 *  writes plus a curve recompute when distDrive changed.  Called from
 *  the params-watching effect below. */
function applyFxParams(n: FxNodes, p: FxParams, prevDistDrive: number): void {
  // Distortion curve only needs to be rebuilt when drive actually
  // changes — the Float32Array allocation is what we save here.
  if (p.distDrive !== prevDistDrive) {
    n.dist.curve = buildDistortionCurve(p.distDrive)
  }

  // Ring mod
  n.ringOsc.frequency.value = p.ringFreq
  n.ringOscAmp.gain.value   = p.ringDepth   // oscillator amplitude scaled by depth

  // Delay — clamp feedback below the runaway threshold.  v0.1.6 left
  // this to the slider max but we re-clamp here as a defense in case
  // a preset or RNG ever lands above 0.95.
  n.delay.delayTime.value = Math.min(Math.max(p.delayTime, 0), 2)
  n.delayFb.gain.value    = Math.min(Math.max(p.delayFb, 0), 0.95)
  n.delayDry.gain.value   = 1 - p.delayMix
  n.delayWet.gain.value   = p.delayMix

  // Phaser — depth controls both LFO amplitude AND wet/dry mix in
  // lockstep, exactly like v0.1.6.
  n.phaseLFO.frequency.value = p.phaseRate
  n.phaseLFOGain.gain.value  = 500 * p.phaseDepth
  n.phaseDry.gain.value      = 1 - p.phaseDepth * 0.5
  n.phaseWet.gain.value      = p.phaseDepth * 0.5
}

/** Build the entire FX chain from scratch.  Connects every node and
 *  starts the oscillators.  Called exactly once per audio element
 *  (per ADR-0003). */
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
    // Most common cause: a previous render bound to this element and
    // we're re-mounting.  Should be impossible given the idempotent
    // hook, but log for debugging.
    // eslint-disable-next-line no-console
    console.error("[fx] createMediaElementSource failed:", e)
    void ctx.close()
    return null
  }

  // ── Distortion ────────────────────────────────────────────────────
  const dist = ctx.createWaveShaper()
  dist.curve = buildDistortionCurve(initial.distDrive)
  dist.oversample = "2x"

  // ── Ring mod ──────────────────────────────────────────────────────
  // Topology: oscillator → ringOscAmp(depth) → ringGain.gain
  //   gain.value (base)        = 1.0  (passthrough)
  //   ringOscAmp output adds    = depth * sin(freq*t)
  //   so net gain               = 1 + depth*sin(t)   (matches Python)
  const ringGain = ctx.createGain()
  ringGain.gain.value = 1.0
  const ringOsc = ctx.createOscillator()
  ringOsc.type = "sine"
  ringOsc.frequency.value = initial.ringFreq
  const ringOscAmp = ctx.createGain()
  ringOscAmp.gain.value = initial.ringDepth
  ringOsc.connect(ringOscAmp)
  ringOscAmp.connect(ringGain.gain)
  ringOsc.start()

  // ── Delay (with feedback loop + dry/wet) ──────────────────────────
  const delay    = ctx.createDelay(2.0)
  const delayFb  = ctx.createGain()
  const delayDry = ctx.createGain()
  const delayWet = ctx.createGain()
  const delayOut = ctx.createGain()
  delay.delayTime.value = initial.delayTime
  delayFb.gain.value    = initial.delayFb
  delayDry.gain.value   = 1
  delayWet.gain.value   = 0
  delay.connect(delayFb)
  delayFb.connect(delay)         // feedback loop
  delay.connect(delayWet)
  delayDry.connect(delayOut)
  delayWet.connect(delayOut)

  // ── Phaser (4 allpass filters with LFO-modulated frequency) ──────
  const phaseAP: BiquadFilterNode[] = []
  for (let i = 0; i < 4; i++) {
    const ap = ctx.createBiquadFilter()
    ap.type = "allpass"
    // Spread the four allpass center frequencies in log space so the
    // sweep covers a useful musical range (200 Hz → ~3.2 kHz).
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

  // ── Wire the full chain ──────────────────────────────────────────
  src.connect(dist)
  dist.connect(ringGain)

  ringGain.connect(delayDry)
  ringGain.connect(delay)

  delayOut.connect(phaseDry)
  delayOut.connect(phaseAP[0])

  phaseAP[phaseAP.length - 1].connect(phaseWet)
  phaseDry.connect(ctx.destination)
  phaseWet.connect(ctx.destination)

  // ── Analyser tap (off the dry phaser output) ─────────────────────
  // Used by the future VU meter / acid halo.  Sampling the dry signal
  // means the level we render matches what the user hears even when
  // the phaser is fully wet.
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 256
  analyser.smoothingTimeConstant = 0.7
  phaseDry.connect(analyser)
  const analyserBuf = new Uint8Array(analyser.frequencyBinCount)

  // ── Resume on play (autoplay-policy workaround) ──────────────────
  // The 'play' event IS a user gesture for autoplay-policy purposes.
  // Resume here, never inside a setInterval / onload — both fail the
  // gesture check on Chromium-based runtimes.
  const onPlay = () => {
    if (ctx.state === "suspended") {
      ctx.resume().catch((e) => {
        // eslint-disable-next-line no-console
        console.warn("[fx] AudioContext.resume() rejected:", e)
      })
    }
  }
  audioEl.addEventListener("play", onPlay)

  // Best-effort early resume — works if the user has already
  // interacted with the page (e.g., they clicked Slurmify earlier).
  if (ctx.state === "suspended") {
    void ctx.resume().catch(() => {/* silently ignored */})
  }

  // eslint-disable-next-line no-console
  console.log(`[fx] chain ready, sr=${ctx.sampleRate}`)

  return {
    ctx,
    dist,
    ringGain, ringOsc, ringOscAmp,
    delay, delayFb, delayDry, delayWet, delayOut,
    phaseAP, phaseLFO, phaseLFOGain, phaseDry, phaseWet,
    analyser, analyserBuf,
  }
}

export interface UseFxChainResult {
  /** True once the chain is bound and the AudioContext exists.
   *  Consumers (like the VU meter) gate on this. */
  ready:    boolean
  /** Live reference to the AnalyserNode for visualizers, or null until
   *  the chain is built. */
  analyser: AnalyserNode | null
  /** Pre-allocated buffer matching `analyser.frequencyBinCount` so
   *  callers can `getByteTimeDomainData(buf)` on every rAF. */
  analyserBuf: Uint8Array | null
}

/**
 * Bind the FX chain to the given audio element exactly once per
 * element lifetime.  Call this from any component that owns a
 * WaveformPlayer whose audio should run through FX (currently the
 * OUTPUT module).
 *
 * Pass `null` while the WaveformPlayer is still mounting and waiting
 * for wavesurfer to construct its underlying <audio>; the hook
 * no-ops until a real element arrives.
 */
export function useFxChain(audioEl: HTMLMediaElement | null): UseFxChainResult {
  // The chain is held in a ref because rebuilding it on every render
  // would re-run createMediaElementSource and crash (see ADR-0003).
  const nodesRef = useRef<FxNodes | null>(null)

  // Track the previous distDrive so applyFxParams can skip the curve
  // rebuild when it didn't change.  Initialized lazily.
  const prevDriveRef = useRef<number>(-1)

  const params = useFxStore((s) => s.params)

  // ── Bind the chain on first real element ─────────────────────────
  useEffect(() => {
    if (!audioEl)            return     // wavesurfer hasn't created the <audio> yet
    if (nodesRef.current)    return     // already bound — idempotent guard
    const nodes = buildFxChain(audioEl, useFxStore.getState().params)
    if (nodes) {
      nodesRef.current = nodes
      prevDriveRef.current = useFxStore.getState().params.distDrive
    }
    // Intentionally NOT returning a cleanup that closes the context —
    // closing wouldn't release the createMediaElementSource binding,
    // and the audioEl outlives this component anyway (wavesurfer
    // keeps it across URL swaps).  Letting the context persist for
    // the page lifetime matches v0.1.6 behavior.
  }, [audioEl])

  // ── Re-apply params on every store update ────────────────────────
  // Cheap; runs at most a handful of times per knob twist (Zustand
  // debounces synchronous setState calls within a tick).
  useEffect(() => {
    if (!nodesRef.current) return
    applyFxParams(nodesRef.current, params, prevDriveRef.current)
    prevDriveRef.current = params.distDrive
  }, [params])

  return {
    ready:       nodesRef.current !== null,
    analyser:    nodesRef.current?.analyser    ?? null,
    analyserBuf: nodesRef.current?.analyserBuf ?? null,
  }
}
