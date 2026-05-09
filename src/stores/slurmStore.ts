// ──────────────────────────────────────────────────────────────────────
// src/stores/slurmStore.ts — Source file + slurmify params + job state
// ──────────────────────────────────────────────────────────────────────
//
// One Zustand store holds everything related to the active slurmify
// session: the uploaded source, the slurm output, the parameters, and
// the in-flight job state.
//
// Phase D1 scope: just sourceFile + the actions to set/clear it.  The
// rest of the schema is sketched in but stubbed — Week 3 fills in
// params + job machinery, and Week 4 fills in fxStore.
//
// What we persist (localStorage):
//   • params — a power user wants their last slider settings to come
//     back on reload.
//   • outputFormat — sticky, like the v0.1.6 dropdown.
//
// What we DON'T persist:
//   • sourceFile / output — these reference file_ids that the backend
//     forgets on restart.  Persisting them would surface ghost
//     references.
//   • job state — purely transient.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

// ── Source file shape ─────────────────────────────────────────────────
// Mirrors the response body of POST /upload (see src-python/api/upload.py).
// Keep these field names identical so the frontend can do
// `setSourceFile(await response.json())` directly.

export interface SourceFile {
  file_id:        string
  name:           string
  was_extracted:  boolean
  duration_sec:   number
  channels:       number
  sample_rate:    number
  format:         string
}

// ── Slurmify output shape ─────────────────────────────────────────────
// Populated when /jobs/{id}/progress closes with output_id set.

export interface SlurmOutput {
  output_id: string
  url:       string   // resolved http://localhost:PORT/files/{output_id}
}

// ── Analysis result ───────────────────────────────────────────────────
// Mirrors GET /analyze/{file_id} response (src-python/api/analyze.py).
//
// Why a separate state slice from `sourceFile` (rather than folding the
// fields into SourceFile)?  The /upload endpoint returns FAST so the
// waveform paints quickly; /analyze runs librosa.beat.beat_track which
// adds 0.5-2s.  We render the source/transport instantly with
// `analysis === null`, then fill in the detected BPM later — the UI
// shows "—" or "(detecting…)" until the analyze fetch resolves.
//
// The bpm field can be null even after analysis completes (silence,
// very short files, pathological inputs).  Consumers MUST treat
// `analysis === null` (not yet detected) and `analysis.bpm === null`
// (detected, no estimate) as distinct states.

export interface AnalysisResult {
  file_id:      string
  duration_sec: number
  channels:     number
  sample_rate:  number
  bpm:          number | null
}

// ── Slurmify parameter shape ──────────────────────────────────────────
// Mirrors SlurmifyRequest in src-python/api/slurmify.py one-for-one.
// Field defaults match v0.1.6 Gradio defaults.  Keep these in sync
// when adding/removing params on either side.

export interface SlurmParams {
  speed:                 number
  resolution:            string
  transient_sensitivity: number
  envelope_ms:           number
  preserve_pitch:        boolean
  pitch_shift_semitones: number

  randomize_order:       boolean
  reverse_chance:        number
  stutter_chance:        number
  stutter_skip_ms:       number
  stutter_max_reps:      number
  stutter_spread:        number

  beat_trim_start_ms:    number
  beat_trim_end_ms:      number
  beat_gap_ms:           number

  // ADR-0020 note-mode counterparts
  stutter_skip_mode:     "ms" | "♪"
  stutter_skip_note:     string
  beat_trim_start_mode:  "ms" | "♪"
  beat_trim_start_note:  string
  beat_trim_end_mode:    "ms" | "♪"
  beat_trim_end_note:    string
  beat_gap_mode:         "ms" | "♪"
  beat_gap_note:         string

  bpm_override:          number | null
  start_sec:             number
  end_sec:               number
  seed:                  number | null
  beat_mask:             boolean[] | null

  output_format:         "wav" | "mp3" | "flac" | "ogg" | "aiff" | "aac"
}

export const defaultSlurmParams = (): SlurmParams => ({
  speed:                 2.0,
  resolution:            "1/16",
  transient_sensitivity: 0.5,
  envelope_ms:           2.0,
  preserve_pitch:        true,
  pitch_shift_semitones: 0,
  randomize_order:       false,
  reverse_chance:        0,
  stutter_chance:        0,
  stutter_skip_ms:       0,
  stutter_max_reps:      0,
  stutter_spread:        0,
  beat_trim_start_ms:    0,
  beat_trim_end_ms:      0,
  beat_gap_ms:           0,
  stutter_skip_mode:     "ms",
  stutter_skip_note:     "1/32",
  beat_trim_start_mode:  "ms",
  beat_trim_start_note:  "1/16",
  beat_trim_end_mode:    "ms",
  beat_trim_end_note:    "1/16",
  beat_gap_mode:         "ms",
  beat_gap_note:         "1/16",
  bpm_override:          null,
  start_sec:             0,
  end_sec:               0,
  seed:                  null,
  beat_mask:             null,
  output_format:         "wav",
})

// ── Job state ─────────────────────────────────────────────────────────
// Tracks an in-flight slurmify (NOT FX burn / video render — those get
// their own job-state slices when we add them in W4 / W5).

export interface JobState {
  jobId:    string | null
  progress: number          // 0-1
  desc:     string
  isRunning: boolean
  error:    string | null
}

const initialJobState: JobState = {
  jobId:     null,
  progress:  0,
  desc:      "",
  isRunning: false,
  error:     null,
}

// ── Store shape ───────────────────────────────────────────────────────

interface SlurmStore extends JobState {
  sourceFile: SourceFile | null
  output:     SlurmOutput | null
  params:     SlurmParams
  // Detected BPM + duration from /analyze/{file_id}.  Populated lazily
  // after the source loads (see SourceModuleBody useEffect).  null = not
  // yet detected; analysis.bpm === null = detected but no estimate
  // available (see AnalysisResult comment above).
  analysis:   AnalysisResult | null

  // ── Actions ──────────────────────────────────────────────────────
  setSourceFile: (s: SourceFile | null) => void
  clearSource:   () => void
  setOutput:     (o: SlurmOutput | null) => void
  setAnalysis:   (a: AnalysisResult | null) => void

  setParam: <K extends keyof SlurmParams>(key: K, value: SlurmParams[K]) => void
  resetParams: () => void

  // ── In/out trim invariant-enforcing actions ──────────────────────
  // The slurmify pipeline expects start_sec < end_sec (or end_sec=0
  // meaning "use full file").  When the user captures IN past the
  // current OUT (or OUT before IN), we auto-correct rather than
  // blindly storing an invalid range:
  //   • captureInPoint(t):  if t >= current end_sec (and end_sec>0),
  //     reset end_sec to 0 — the user is starting a fresh selection.
  //   • captureOutPoint(t): if t <= current start_sec, reset
  //     start_sec to 0 — symmetric correction.
  // Both clamp t to [0, durationSec].
  captureInPoint:  (t: number, durationSec: number) => void
  captureOutPoint: (t: number, durationSec: number) => void
  clearInOut: () => void

  // Job lifecycle (used in W3 when we wire /slurmify + SSE)
  startJob:  (jobId: string) => void
  updateJob: (p: { progress: number; desc: string }) => void
  finishJob: (output: SlurmOutput | null, error: string | null) => void
}

export const useSlurmStore = create<SlurmStore>()(
  persist(
    (set) => ({
      sourceFile: null,
      output:     null,
      params:     defaultSlurmParams(),
      analysis:   null,
      ...initialJobState,

      setSourceFile: (s) => set((state) => ({
        sourceFile: s,
        // Clear stale output/job/analysis whenever source changes — the
        // previous slurm + BPM detection referred to a different audio.
        output:   null,
        analysis: null,
        // Clear PER-FILE params: start_sec / end_sec are sample
        // positions into a specific recording (not a preference), and
        // beat_mask is sized to the previous file's slice grid.
        // Carrying any of them over to a new source produces silent
        // garbage — e.g. an end_sec past the new file's duration, or
        // a mask that mutes random slices that no longer correspond
        // to the same musical positions.
        // Other params (speed, resolution, knob values, output_format)
        // ARE user preferences and stay in place; this matches v0.1.6
        // where loading a new file kept your slider settings.
        params: {
          ...state.params,
          start_sec: 0,
          end_sec:   0,
          beat_mask: null,
        },
        ...initialJobState,
      })),

      clearSource: () => set((state) => ({
        sourceFile: null,
        output:     null,
        analysis:   null,
        params: {
          ...state.params,
          start_sec: 0,
          end_sec:   0,
          beat_mask: null,
        },
        ...initialJobState,
      })),

      setOutput:   (o) => set({ output: o }),
      setAnalysis: (a) => set({ analysis: a }),

      setParam: (key, value) =>
        set((s) => ({ params: { ...s.params, [key]: value } })),

      resetParams: () => set({ params: defaultSlurmParams() }),

      captureInPoint: (t, durationSec) =>
        set((s) => {
          const tClamped = Math.max(0, Math.min(t, durationSec))
          const currentOut = s.params.end_sec
          // If new IN lands past current OUT, clear OUT (auto-correct
          // — treats the keypress as "starting a fresh selection").
          // tolerance 0.001 so an exact-boundary capture still
          // produces a valid window.
          const nextOut = (currentOut > 0 && tClamped >= currentOut - 0.001)
            ? 0
            : currentOut
          return {
            params: {
              ...s.params,
              start_sec: tClamped,
              end_sec:   nextOut,
            },
          }
        }),

      captureOutPoint: (t, durationSec) =>
        set((s) => {
          const tClamped = Math.max(0, Math.min(t, durationSec))
          const currentIn = s.params.start_sec
          // Symmetric: OUT before IN → reset IN to 0.
          const nextIn = (currentIn > 0 && tClamped <= currentIn + 0.001)
            ? 0
            : currentIn
          return {
            params: {
              ...s.params,
              start_sec: nextIn,
              end_sec:   tClamped,
            },
          }
        }),

      clearInOut: () =>
        set((s) => ({
          params: { ...s.params, start_sec: 0, end_sec: 0 },
        })),

      startJob: (jobId) => set({
        jobId,
        progress:  0,
        desc:      "",
        isRunning: true,
        error:     null,
      }),

      updateJob: ({ progress, desc }) => set({ progress, desc }),

      finishJob: (output, error) => set((_s) => ({
        output:    output,
        error:     error,
        isRunning: false,
        progress:  output ? 1 : 0,
      })),
    }),
    {
      name: "slurmify_session_v2",
      // Only the user-meaningful preference (params) and output format
      // need to survive reloads.  sourceFile + output + job state stay
      // transient because they reference backend file_ids that the
      // sidecar forgets on restart.
      partialize: (s) => ({ params: s.params }),
    },
  ),
)
