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

export interface FxParams {
  // ── Distortion (WaveShaper with tanh curve) ──────────────────────
  /** Drive amount.  0 = bypass.  1 = heavy clipping.  Maps to the
   *  curve constant k = 1 + drive * 29 in _fxCurve. */
  distDrive: number

  // ── Ring modulator (sine osc → gain.gain) ─────────────────────────
  /** Carrier frequency in Hz.  Sub-100 = tremolo flutter.  100-500 =
   *  classic ring-mod metallic.  500+ = inharmonic crunch. */
  ringFreq: number
  /** Modulation depth.  0 = bypass (gain stays at 1).  1 = full ring
   *  modulation. */
  ringDepth: number

  // ── Delay (DelayNode + feedback gain + dry/wet) ──────────────────
  /** Delay time in seconds.  0–2 (DelayNode max). */
  delayTime: number
  /** Feedback gain.  0 = single repeat.  ~0.9 = self-oscillating
   *  drone.  Clamp ≤ 0.95 to avoid runaway. */
  delayFb: number
  /** Wet/dry mix.  0 = bypass.  1 = full wet (no dry signal). */
  delayMix: number

  // ── Phaser (4 allpass filters + LFO) ─────────────────────────────
  /** LFO rate in Hz.  0.05 = slow sweep (~20 s).  5+ = throbbing. */
  phaseRate: number
  /** Phaser depth.  0 = bypass.  1 = full sweep + balanced wet/dry
   *  (matches v0.1.6's 0.5/0.5 mix when depth=1). */
  phaseDepth: number
}

export const defaultFxParams = (): FxParams => ({
  distDrive:  0,
  ringFreq:   200,
  ringDepth:  0,
  delayTime:  0.3,
  delayFb:    0.35,
  delayMix:   0,
  phaseRate:  1.0,
  phaseDepth: 0,
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
      name: "slurmify_fx_session_v1",
      // Only the user-meaningful preferences (knob positions) survive
      // reloads.  Burn-job state stays transient because burnedFileId
      // references a backend-side file that's gone after a sidecar
      // restart.
      partialize: (s) => ({ params: s.params }),
    },
  ),
)
