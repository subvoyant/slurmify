// ──────────────────────────────────────────────────────────────────────
// src/stores/uiPrefsStore.ts — Global UI preferences (tooltips + eggs)
// ──────────────────────────────────────────────────────────────────────
//
// Tiny persisted store for two user-facing toggles that affect the
// whole app's UI behavior:
//
//   • tooltipsEnabled   — when false, every <Tip> render short-circuits
//                          to render its child unwrapped.  Useful for
//                          power users who've internalized the controls
//                          and want a quieter UI, OR for screen recording
//                          where stray hover tooltips clutter the take.
//
//   • easterEggsEnabled — when false, every EasterEggHover render
//                          short-circuits and just renders its child
//                          without the hover-gif overlay.  Same use
//                          cases (quiet UI, clean recording), plus
//                          the "I love this app but I've seen Bob
//                          enough times today" case.
//
// Both default ON because the eggs and tooltips are part of the app's
// personality — you discover Bob, MaxFire, and the verbose hint copy
// the first few sessions, then opt out if you want to.
//
// Persisted under "slurmify_ui_prefs_v1" so the choice survives
// reloads.  Tiny payload; no migration logic needed for a fresh store.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

interface UiPrefsStore {
  /** When true (default), tooltips render normally on hover.  When
   *  false, every <Tip> wrapper renders its child without the
   *  Radix tooltip plumbing — no hover popups, no a11y noise. */
  tooltipsEnabled: boolean

  /** When true (default), EasterEggHover renders the gif overlay on
   *  hover.  When false, it returns the child element unwrapped (no
   *  portal, no DOMRect measurement, no GIF preload). */
  easterEggsEnabled: boolean

  setTooltipsEnabled:   (v: boolean) => void
  setEasterEggsEnabled: (v: boolean) => void
}

export const useUiPrefsStore = create<UiPrefsStore>()(
  persist(
    (set) => ({
      tooltipsEnabled:   true,
      easterEggsEnabled: true,

      setTooltipsEnabled:   (v) => set({ tooltipsEnabled:   v }),
      setEasterEggsEnabled: (v) => set({ easterEggsEnabled: v }),
    }),
    {
      name: "slurmify_ui_prefs_v1",
    },
  ),
)
