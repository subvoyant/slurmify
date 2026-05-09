// ──────────────────────────────────────────────────────────────────────
// postcss.config.js — PostCSS pipeline for Vite
// ──────────────────────────────────────────────────────────────────────
// Runs Tailwind's JIT compiler on every CSS file Vite processes, then
// autoprefixer adds vendor prefixes for any non-evergreen browser
// quirks.  Tauri's WebView is always Chromium-or-Safari recent, so
// autoprefixer is mostly a no-op — kept for safety + parity with
// browser-side dev (e.g., opening http://localhost:1420 in Safari for
// debugging).
// ──────────────────────────────────────────────────────────────────────

export default {
  plugins: {
    tailwindcss:  {},
    autoprefixer: {},
  },
}
