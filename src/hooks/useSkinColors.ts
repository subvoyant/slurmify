// ──────────────────────────────────────────────────────────────────────
// src/hooks/useSkinColors.ts — Resolved CSS-variable colors for canvas
// ──────────────────────────────────────────────────────────────────────
//
// Why this hook exists: HTML5 Canvas (used by WaveSurfer, future XY
// pads, future spectrograms) does NOT resolve CSS `var()` references
// when passed as a fillStyle / strokeStyle.  Passing
// `"var(--slurm-cyan)"` results in a fallback color (typically black).
//
// Workaround: read the COMPUTED hex value from <html> via
// getComputedStyle() and re-read whenever the active skin changes.
// Components that render to canvas use these resolved values;
// components that render to DOM keep using the var() refs directly
// (which CSS does resolve).
//
// Usage:
//   const colors = useSkinColors()
//   <canvas onMount={ctx => ctx.fillStyle = colors.cyan} />
//
// The returned object is referentially STABLE within a skin — same
// object reference across renders unless the skin changed.  Safe to
// use in useEffect dependencies.
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react"
import { useSkinStore } from "@/stores/skinStore"

export interface SkinColors {
  bg:        string
  fg:        string
  muted:     string
  cyan:      string
  orange:    string
  rose:      string
  surface:   string
  surface2:  string
  border:    string
  border2:   string
  ok:        string
  warn:      string
  danger:    string
}

const VARIABLE_NAMES: Record<keyof SkinColors, string> = {
  bg:       "--slurm-bg",
  fg:       "--slurm-fg",
  muted:    "--slurm-muted",
  cyan:     "--slurm-cyan",
  orange:   "--slurm-orange",
  rose:     "--slurm-rose",
  surface:  "--slurm-surface",
  surface2: "--slurm-surface2",
  border:   "--slurm-border",
  border2:  "--slurm-border-2",
  ok:       "--slurm-ok",
  warn:     "--slurm-warn",
  danger:   "--slurm-danger",
}

function readSkinColors(): SkinColors {
  // Defensive default — runs in test envs where document is undefined.
  if (typeof document === "undefined") {
    return Object.fromEntries(
      Object.keys(VARIABLE_NAMES).map((k) => [k, "#000000"]),
    ) as SkinColors
  }
  const styles = getComputedStyle(document.documentElement)
  const out = {} as SkinColors
  for (const [key, varName] of Object.entries(VARIABLE_NAMES)) {
    // .trim() because CSS values often come back with leading
    // whitespace ("  #00b9e1").
    out[key as keyof SkinColors] = styles.getPropertyValue(varName).trim()
  }
  return out
}

export function useSkinColors(): SkinColors {
  // Re-read whenever the active skin changes.  We depend on the
  // skinStore's `skin` field as a dependency — changing skins flips
  // the data-skin attribute on <html>, then this effect runs and
  // pulls the new computed values.
  const skin = useSkinStore((s) => s.skin)
  const [colors, setColors] = useState<SkinColors>(() => readSkinColors())

  useEffect(() => {
    // Defer one frame so the DOM has actually applied the new
    // data-skin attribute before we read computed styles.  Without
    // this, the FIRST read after a skin switch can return the
    // old skin's values.
    const id = requestAnimationFrame(() => {
      setColors(readSkinColors())
    })
    return () => cancelAnimationFrame(id)
  }, [skin])

  return colors
}
