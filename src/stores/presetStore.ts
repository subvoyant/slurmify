// ──────────────────────────────────────────────────────────────────────
// src/stores/presetStore.ts — User-saved slurm presets + apply action
// ──────────────────────────────────────────────────────────────────────
//
// Persists user-created presets across sessions and provides the two
// actions the PresetBar UI needs:
//
//   • savePreset(name)    — capture current SlurmParams under a name.
//                           Refuses factory ids; overwrites prior user
//                           preset of the same name.
//   • applyPreset(id)     — patch slurmStore.params with the preset's
//                           data, leaving per-file fields alone.
//   • deletePreset(name)  — remove a user preset.
//
// Why a SEPARATE store from slurmStore?
//   slurmStore.params is the LIVE editing state — every knob twist
//   writes there.  The preset library is a small, slowly-changing
//   collection.  Splitting them keeps the persist partialize logic
//   simpler in both stores and lets us version the preset schema
//   independently if we ever migrate it.
//
// Storage format (localStorage key: slurmify_user_presets_v1):
//
//   {
//     userPresets: {
//       "my crunchy chop": { speed: 2.0, resolution: "1/16", ... },
//       "ambient slow":     { speed: 0.5, ... },
//     },
//     activePresetId: "factory:canonical" | "user:my crunchy chop" | null
//   }
//
// `activePresetId` is sticky across reloads so the user sees their
// last-selected preset on app restart, even though the actual params
// also persisted independently in slurmStore.  If the active preset's
// data drifts from the live params (because the user twisted a knob),
// we mark the preset as "dirty" — the dropdown shows "(modified)"
// next to the name.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

import {
  type SlurmPresetData,
  extractPresetData,
  FACTORY_PRESET_IDS,
  findFactoryPreset,
} from "@/lib/factory-presets"
import { useSlurmStore } from "@/stores/slurmStore"

/** Active-preset id is namespaced so factory and user presets can
 *  share names without colliding.  null = "no preset selected" (the
 *  user has been freely editing without picking from the dropdown). */
export type ActivePresetId =
  | { kind: "factory"; id: string }
  | { kind: "user";    name: string }
  | null

interface PresetStore {
  /** name → preset data.  Names are user-supplied and case-sensitive. */
  userPresets: Record<string, SlurmPresetData>

  /** What's currently selected in the dropdown.  Sticky across reloads. */
  activePresetId: ActivePresetId

  // ── Actions ──────────────────────────────────────────────────────
  /** Save current SlurmParams under a user-supplied name.  Throws if
   *  the name collides with a factory id.  Overwrites prior user
   *  preset of the same name silently (the UI confirms before calling
   *  this in that case). */
  savePreset: (name: string) => void

  /** Apply a factory or user preset's data to slurmStore.params.
   *  Per-file fields (start_sec, end_sec, seed, bpm_override,
   *  beat_mask) are left untouched. */
  applyPreset: (id: ActivePresetId) => void

  /** Delete a user preset.  No-op if the name doesn't exist or is a
   *  factory id (factory presets are read-only). */
  deletePreset: (name: string) => void

  /** Reset the dropdown to "no preset selected" — used when the user
   *  twists a knob after picking a preset and we want to flag the
   *  divergence.  Does NOT touch the saved presets themselves. */
  clearActivePreset: () => void
}

export const usePresetStore = create<PresetStore>()(
  persist(
    (set, _get) => ({
      userPresets:    {},
      activePresetId: null,

      savePreset: (name) => {
        const trimmed = name.trim()
        if (!trimmed) {
          throw new Error("preset name cannot be empty")
        }
        if (FACTORY_PRESET_IDS.has(trimmed)) {
          // Block accidental shadowing of a built-in name.  The UI
          // also pre-validates this, but defense in depth.
          throw new Error(
            `"${trimmed}" is a factory preset name — pick a different label.`,
          )
        }
        // Pull the current live params from slurmStore.  Using
        // getState() (not a hook) since this runs outside a render.
        const liveParams = useSlurmStore.getState().params
        const data = extractPresetData(liveParams)
        set((s) => ({
          userPresets: { ...s.userPresets, [trimmed]: data },
          // Saving auto-selects the new preset so the dropdown
          // reflects what was just captured.
          activePresetId: { kind: "user", name: trimmed },
        }))
      },

      applyPreset: (id) => {
        if (id === null) {
          // Selecting "(none)" — just clear the active id without
          // touching params.
          set({ activePresetId: null })
          return
        }
        let data: SlurmPresetData | null = null
        if (id.kind === "factory") {
          const fp = findFactoryPreset(id.id)
          if (fp) data = fp.data
        } else {
          data = _get().userPresets[id.name] ?? null
        }
        if (!data) {
          // Stale id — preset was deleted or factory id renamed.
          // Clear the selection silently rather than throwing; the
          // UI already validated the dropdown options.
          set({ activePresetId: null })
          return
        }
        // Patch slurmStore.params, preserving per-file fields.
        const slurm = useSlurmStore.getState()
        const merged = {
          ...slurm.params,
          ...data,
          // Re-assert per-file fields from the LIVE params — `data`
          // doesn't include them, but spreading first then
          // re-asserting is paranoid-safe in case the type ever
          // drifts.
          bpm_override:  slurm.params.bpm_override,
          start_sec:     slurm.params.start_sec,
          end_sec:       slurm.params.end_sec,
          seed:          slurm.params.seed,
          beat_mask:     slurm.params.beat_mask,
        }
        useSlurmStore.setState({ params: merged })
        set({ activePresetId: id })
      },

      deletePreset: (name) => {
        if (FACTORY_PRESET_IDS.has(name)) {
          // Factory presets are read-only.  Silently ignore.
          return
        }
        set((s) => {
          if (!(name in s.userPresets)) return s
          const next = { ...s.userPresets }
          delete next[name]
          return {
            userPresets: next,
            // If the deleted preset was active, clear the dropdown.
            activePresetId:
              s.activePresetId?.kind === "user" && s.activePresetId.name === name
                ? null
                : s.activePresetId,
          }
        })
      },

      clearActivePreset: () => set({ activePresetId: null }),
    }),
    {
      name: "slurmify_user_presets_v1",
      // Both fields are user-meaningful and should survive reloads.
      partialize: (s) => ({
        userPresets:    s.userPresets,
        activePresetId: s.activePresetId,
      }),
    },
  ),
)

/**
 * Compare the supplied params against the active preset's data.
 * Returns true when they DIFFER — used to flag the dropdown as
 * "(modified)" so the user knows their tweaks aren't captured.
 *
 * Lives in the store module rather than the component because the
 * preset lookup logic (factory vs. user, missing-id fallback) is the
 * same as inside applyPreset; keeping them together prevents drift.
 */
export function isPresetModified(
  active: ActivePresetId,
  liveParams: ReturnType<typeof useSlurmStore.getState>["params"],
): boolean {
  if (active === null) return false
  let data: SlurmPresetData | null = null
  if (active.kind === "factory") {
    data = findFactoryPreset(active.id)?.data ?? null
  } else {
    data = usePresetStore.getState().userPresets[active.name] ?? null
  }
  if (!data) return false   // missing preset — no comparison possible
  const live = extractPresetData(liveParams)
  // Compare key-by-key.  All values are primitives or null/undefined
  // in SlurmPresetData (no arrays — beat_mask is excluded), so
  // referential equality is sufficient.
  for (const key of Object.keys(data) as (keyof SlurmPresetData)[]) {
    if (data[key] !== live[key]) return true
  }
  return false
}
