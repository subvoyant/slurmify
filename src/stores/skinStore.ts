// ──────────────────────────────────────────────────────────────────────
// src/stores/skinStore.ts — Zustand store for the active skin
// ──────────────────────────────────────────────────────────────────────
//
// Three skins coexist in CSS via :root[data-skin="…"] variable blocks
// in globals.css.  This store is the single React-side source of truth
// for which one is active, with two responsibilities:
//
//   1. Sync the `data-skin` attribute on <html> whenever the active
//      skin changes — that's what triggers the CSS variable swap.
//   2. Persist the user's choice across reloads via localStorage.
//
// Storage key: "slurmify_skin_v2".
//
// Why not reuse v0.1.6's "slurm_skin" key (ADR-0007)?
//   The v0.1.6 entry is a raw string ("acid"); Zustand's persist
//   middleware writes JSON ({"state":{"skin":"acid"},"version":0}).
//   Sharing the key would corrupt either side on round-trip.  v0.2.0
//   gets a fresh key; users see their skin reset to "default" the
//   first time they launch v0.2.0.  Mild UX wart; cleanest fix.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

export type Skin = "default" | "acid" | "hardware"

export const SKIN_OPTIONS: { value: Skin; label: string }[] = [
  { value: "default",  label: "subvoyant · default" },
  { value: "acid",     label: "acid cathedral" },
  { value: "hardware", label: "hardware rack" },
]

interface SkinStore {
  skin: Skin
  setSkin: (skin: Skin) => void
}

/**
 * Apply the skin to <html data-skin="…">.  Called from setSkin AND from
 * the initial bootstrap in App.tsx so the saved skin is reflected
 * before first paint.  Also accepts a fallback for SSR safety even
 * though we never actually run server-side.
 */
function applySkinToDOM(skin: Skin): void {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.skin = skin
  }
}

export const useSkinStore = create<SkinStore>()(
  persist(
    (set) => ({
      skin: "default",
      setSkin: (skin) => {
        applySkinToDOM(skin)
        set({ skin })
      },
    }),
    {
      name: "slurmify_skin_v2",
      // Re-apply the saved skin to the DOM on hydration so reloads
      // start in the right skin without a flash of the default.
      onRehydrateStorage: () => (state) => {
        if (state?.skin) applySkinToDOM(state.skin)
      },
    },
  ),
)
