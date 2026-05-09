// ──────────────────────────────────────────────────────────────────────
// src/lib/rack-colors.ts — Per-module identity colors for the rack UI
// ──────────────────────────────────────────────────────────────────────
//
// Each Slurmify rack module has a stable identity color.  These colors
// do NOT change per skin — the module identity is meant to be visually
// stable (a Thor synth is teal in any rack/skin context, the same way
// our SLICING module is always teal).  Only the body colors below the
// header re-tint with the active skin.
//
// Naming + values follow docs/UI_DESIGN_BRIEF.md §9.  Inspired by the
// Reason device color taxonomy:
//   • Dr.OctoRex (orange)  → INPUT
//   • Thor (deep teal)     → SLICING
//   • Mimic (sandy beige)  → STRETCH
//   • Umpf (warm wood)     → BEAT TRIM
//   • DDL (red glitch)     → STUTTER
//   • Ripley (deep blue)   → FX
//   • generic LED green    → OUTPUT
//   • cinema purple        → VIDEO (export-to-MP4)
//
// Each entry has:
//   • header — the bg color of the rack module's header bar
//   • dot    — slightly brighter for the pulsing status dot (8% boost)
//   • on     — solid identity (used for borders / mute-strip strip)
// ──────────────────────────────────────────────────────────────────────

export interface RackColor {
  /** Header bar background (also the right-edge brand strip color). */
  header: string
  /** Status dot color — slightly brighter for visibility. */
  dot:    string
  /** Solid identity for borders / accents. */
  on:     string
}

export const RACK_COLORS = {
  input:    { header: "#9e5a18", dot: "#e89a4c", on: "#c47a2c" },
  slicing:  { header: "#1f5d68", dot: "#5cb4c4", on: "#2c7c8c" },
  stretch:  { header: "#7a6740", dot: "#c4a875", on: "#a08855" },
  trim:     { header: "#7c4250", dot: "#cc8898", on: "#a05a6a" },
  stutter:  { header: "#8a3320", dot: "#e87654", on: "#bc4a30" },
  fx:       { header: "#2a426c", dot: "#6a8acc", on: "#3a5a90" },
  output:   { header: "#286a34", dot: "#5cba6c", on: "#3a8c4a" },
  video:    { header: "#4a2a6c", dot: "#a86ccc", on: "#6a3a90" },
} as const

export type RackColorKey = keyof typeof RACK_COLORS
