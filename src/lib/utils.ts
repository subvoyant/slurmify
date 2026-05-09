// ──────────────────────────────────────────────────────────────────────
// src/lib/utils.ts — shadcn's `cn()` helper + small utilities
// ──────────────────────────────────────────────────────────────────────
//
// `cn()` merges class strings safely:
//   • clsx() — accepts strings, arrays, conditional objects, falsy values
//             and produces a single space-separated string.
//   • twMerge() — resolves Tailwind class conflicts (e.g., `p-2 p-4` →
//             `p-4`; the LAST one wins).  Without this, conditional
//             className composition produces broken output where two
//             padding classes both end up in the DOM and the cascade
//             picks an arbitrary one.
//
// Usage:
//   <div className={cn("p-2 text-slurm-cyan", isActive && "bg-slurm-surface", className)} />
//
// This is the same `cn()` shadcn's CLI generates and every shadcn
// primitive imports.  Re-exporting here keeps the import path stable:
//   import { cn } from "@/lib/utils"
// ──────────────────────────────────────────────────────────────────────

import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ── formatTime ────────────────────────────────────────────────────────
// Used by WaveformPlayer + clock display.  Mirrors the
// "M:SS.cs" format from v0.1.6's INIT_JS clock loop.

export function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "0:00.00"
  const m = Math.floor(seconds / 60)
  const s = (seconds % 60).toFixed(2)
  return `${m}:${s.padStart(5, "0")}`
}

// ── formatBytes ───────────────────────────────────────────────────────
// For file-size displays in the upload + output panels.

export function formatBytes(bytes: number): string {
  if (bytes < 1024)            return `${bytes} B`
  if (bytes < 1024 * 1024)     return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3)       return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return                              `${(bytes / 1024 ** 3).toFixed(2)} GB`
}
