// ──────────────────────────────────────────────────────────────────────
// tailwind.config.ts — Tailwind 3.4 config for the Slurmify frontend
// ──────────────────────────────────────────────────────────────────────
//
// Two color systems coexist (intentionally — see ADR-0007 + ADR-0022):
//
//   1. The "slurm" palette — explicit Subvoyant brand colors exposed
//      as CSS custom properties (e.g., --slurm-cyan).  Use these
//      whenever you want a specific brand color regardless of skin —
//      they are SAME across all skins.  Tailwind class:  bg-slurm-cyan,
//      text-slurm-rose, border-slurm-border, …
//
//   2. The shadcn-flavored token palette — semantic tokens like
//      --background, --foreground, --primary, --muted defined in HSL
//      so Tailwind opacity modifiers work (bg-primary/50).  These
//      DO change per skin — they are how shadcn primitives pick up
//      the active skin automatically.  Tailwind class:  bg-background,
//      text-foreground, bg-primary, …
//
// We define both so:
//   • Hand-written components can use whichever style is more readable
//     in context.
//   • shadcn primitives copied from the registry work without
//     modification (they expect the semantic tokens).
//
// The actual color values live in src/styles/globals.css — this file
// just exposes them to Tailwind's class generator.
// ──────────────────────────────────────────────────────────────────────

import type { Config } from "tailwindcss"
import animate from "tailwindcss-animate"

const config: Config = {
  // Tailwind scans these paths to find class names that need to be
  // generated.  Adding a new directory of TSX files?  Add it here.
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],

  // shadcn's primitives use the `dark:` variant; we don't toggle dark
  // mode — Slurmify is dark-themed always — but we set "class" so the
  // dark: classes still match (we just always have `dark` on <html>).
  darkMode: "class",

  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        // ── Slurm brand palette ────────────────────────────────────
        slurm: {
          bg:         "var(--slurm-bg)",
          fg:         "var(--slurm-fg)",
          muted:      "var(--slurm-muted)",
          cyan:       "var(--slurm-cyan)",
          orange:     "var(--slurm-orange)",
          rose:       "var(--slurm-rose)",
          surface:    "var(--slurm-surface)",
          surface2:   "var(--slurm-surface2)",
          border:     "var(--slurm-border)",
          "border-2": "var(--slurm-border-2)",
          ok:         "var(--slurm-ok)",      // green for "ready" status
          warn:       "var(--slurm-warn)",    // amber for "checking"
          danger:     "var(--slurm-danger)",  // red for errors
        },

        // ── shadcn semantic tokens (HSL form) ─────────────────────
        // Tailwind's color function expects `hsl(var(--token))`; we
        // store the H/S/L triplet (e.g. "192 100% 44%") in the var
        // and Tailwind wraps it.  Don't include the `hsl()` part in
        // the var itself.
        border:        "hsl(var(--border))",
        input:         "hsl(var(--input))",
        ring:          "hsl(var(--ring))",
        background:    "hsl(var(--background))",
        foreground:    "hsl(var(--foreground))",
        primary: {
          DEFAULT:    "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT:    "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT:    "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT:    "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT:    "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT:    "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT:    "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        // shadcn uses these three; lg ≈ 0.5rem by default but we want
        // the slightly tighter 6px to match v0.1.6's compact aesthetic.
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        // Simple pulse-glow animation used by the connection indicator's
        // dot.  Kept here (not as a one-off in App.tsx) so other
        // components can reuse it.
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 6px var(--slurm-cyan)" },
          "50%":      { boxShadow: "0 0 14px var(--slurm-cyan)" },
        },
        "fade-in": {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "fade-in":    "fade-in 220ms ease-out",
      },
    },
  },

  plugins: [
    // tailwindcss-animate is a shadcn dependency — enables `animate-in`,
    // `fade-in-0`, `slide-in-from-top`, etc.  Useful for accordion /
    // dialog / popover transitions.
    animate,
  ],
}

export default config
