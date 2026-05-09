// ──────────────────────────────────────────────────────────────────────
// src/lib/factory-presets.ts — Built-in slurm flavor presets
// ──────────────────────────────────────────────────────────────────────
//
// A preset captures a "flavor" of slurmify — speed, resolution, knob
// values, note-mode toggles, output format — so the user can flip
// between identities (canonical 2× slurm vs. MAX RANDOM chaos vs.
// gentle stretch) without rebuilding the panel each time.
//
// What a preset does NOT include — by design:
//
//   • start_sec / end_sec   — sample positions into a specific file
//   • beat_mask              — sized to the previous file's slice grid
//   • seed                   — empty by default = fresh randomness
//   • bpm_override           — file-specific tempo correction
//
// These are PER-FILE concerns and don't carry meaningfully across
// sources.  The presetStore's `applyPreset` action skips them.
//
// Factory presets are READ-ONLY entries shipped with the app.  Users
// can't overwrite or delete them; they're always at the top of the
// dropdown.  User-created presets live in presetStore.userPresets and
// appear below a divider.
// ──────────────────────────────────────────────────────────────────────

import {
  defaultSlurmParams,
  type SlurmParams,
} from "@/stores/slurmStore"

/**
 * The fields a preset captures — every SlurmParams field EXCEPT the
 * per-file ones listed above.  Using a Pick ensures the type tracks
 * SlurmParams: if someone adds a new param to SlurmParams, this Pick
 * fails to compile until they decide whether the new field is per-
 * file (skip) or a flavor (add).
 */
export type SlurmPresetData = Omit<
  SlurmParams,
  "bpm_override" | "start_sec" | "end_sec" | "seed" | "beat_mask"
>

/**
 * Pull the preset-relevant fields out of a SlurmParams blob.  Used by
 * "Save As" to capture the current state.  The reverse direction
 * (apply a preset back into params) lives in presetStore.applyPreset.
 */
export function extractPresetData(p: SlurmParams): SlurmPresetData {
  // Spread + delete the per-file fields rather than listing all kept
  // fields — fewer maintenance errors when SlurmParams grows.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { bpm_override, start_sec, end_sec, seed, beat_mask, ...preset } = p
  return preset
}

export interface FactoryPreset {
  /** Stable id used as the dropdown value.  Don't rename existing
   *  ids — saved-state references would break. */
  id:          string
  /** Human-readable name shown in the dropdown. */
  name:        string
  /** One-line tooltip explanation. */
  description: string
  /** The captured params.  Built from defaultSlurmParams() + overrides
   *  so we don't have to list every field on every preset — a
   *  factory preset only declares what's DIFFERENT from default. */
  data:        SlurmPresetData
}

// Helper — `defaultSlurmParams()` returns a full SlurmParams; we strip
// per-file fields once and then layer overrides on top of THAT.
const _baseDefaults: SlurmPresetData = extractPresetData(defaultSlurmParams())

/**
 * Build a factory preset from a partial overrides set.  Saves the
 * `...basePreset, ...overrides` boilerplate at every callsite.
 */
function preset(
  id: string,
  name: string,
  description: string,
  overrides: Partial<SlurmPresetData>,
): FactoryPreset {
  return { id, name, description, data: { ..._baseDefaults, ...overrides } }
}

/**
 * The factory preset list — appears at the top of the preset
 * dropdown, in this order.  Order is editorial: most-used first.
 */
export const FACTORY_PRESETS: FactoryPreset[] = [
  preset(
    "default",
    "default",
    "All knobs at their factory defaults — what you get on first launch (2× speed, 1/16 slices, no stutter, no trim).",
    {},  // pure defaults
  ),
  preset(
    "canonical",
    "2× canonical",
    "The signature slurm: 2× speed, 1/16 grid, pitch preserved, full slice envelope. Same as default — kept as an explicit name for muscle memory.",
    {
      speed:                 2.0,
      resolution:            "1/16",
      preserve_pitch:        true,
      envelope_ms:           2.0,
      transient_sensitivity: 0.5,
    },
  ),
  preset(
    "glitch-1-16",
    "1/16 glitch",
    "Tight rhythmic stutter on every other slice; 1/16 grid; small CD-skip stutters. Good starting point for percussive material.",
    {
      speed:                 2.0,
      resolution:            "1/16",
      stutter_chance:        0.5,
      stutter_skip_ms:       30,
      stutter_max_reps:      4,
      stutter_spread:        0.3,
    },
  ),
  preset(
    "max-chaos",
    "MAX RANDOM chaos",
    "Trimodal slice durations (stutter / chop / held buckets) with shuffle on, full envelope, light stutter. Maximum entropy.",
    {
      speed:                 2.0,
      resolution:            "MAX RANDOM",
      randomize_order:       true,
      stutter_chance:        0.3,
      stutter_max_reps:      6,
      stutter_spread:        0.7,
      reverse_chance:        0.15,
      envelope_ms:           5.0,
    },
  ),
  preset(
    "gentle-stretch",
    "gentle stretch",
    "Half-speed time-stretch with pitch preserved and longer envelopes. No stutter, no trim — clean ambient slowdown.",
    {
      speed:                 0.5,
      resolution:            "1/4",
      preserve_pitch:        true,
      envelope_ms:           10.0,
      transient_sensitivity: 0.2,
    },
  ),
  preset(
    "phrase-loop",
    "phrase loop",
    "Long slices (1/2 grid) with high reverse chance and long stutter skips. Turns melodic phrases into mirrored loop fragments.",
    {
      speed:                 1.0,
      resolution:            "1/2",
      reverse_chance:        0.5,
      stutter_chance:        0.4,
      stutter_skip_ms:       250,
      stutter_max_reps:      3,
      stutter_spread:        0.5,
      envelope_ms:           8.0,
    },
  ),
  preset(
    "beat-pocket",
    "beat pocket",
    "Half-beat gap inserted between slices, trim end on every slice — staccato pocket feel. Pairs well with drum breaks.",
    {
      speed:                 1.0,
      resolution:            "1/8",
      beat_gap_mode:         "♪",
      beat_gap_note:         "1/16",
      beat_trim_end_ms:      40,
      envelope_ms:           3.0,
    },
  ),
]

/** Look up a factory preset by id; null if unknown. */
export function findFactoryPreset(id: string): FactoryPreset | null {
  return FACTORY_PRESETS.find((p) => p.id === id) ?? null
}

/** All factory ids, for "is this name colliding with a factory?" checks. */
export const FACTORY_PRESET_IDS = new Set(FACTORY_PRESETS.map((p) => p.id))
