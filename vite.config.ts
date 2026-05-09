// ──────────────────────────────────────────────────────────────────────
// vite.config.ts — Vite 5 config for the Slurmify React frontend
// ──────────────────────────────────────────────────────────────────────
//
// The frontend lives in src/ and is consumed by the Tauri shell in
// src-tauri/.  Vite serves dev mode at http://localhost:1420 (the port
// Tauri expects by default — set in src-tauri/tauri.conf.json).
//
// Two non-default things:
//   1. server.strictPort: error out if 1420 is taken instead of
//      silently falling back to a random port — Tauri can't find us
//      if the port drifts.
//   2. server.watch.ignored: don't watch the Python backend (src-python/)
//      or the Rust shell (src-tauri/) for changes.  Vite would otherwise
//      kick HMR rebuilds every time we edit Python — pointless and slow.
// ──────────────────────────────────────────────────────────────────────

import { defineConfig } from "vite"
import react from "@vitejs/plugin-react-swc"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))

// Tauri's default frontend dev port. The Rust shell's `devUrl` matches
// this — keep them in sync.
const TAURI_DEV_PORT = 1420

export default defineConfig({
  plugins: [react()],

  // Tauri expects a fixed dev port. strictPort makes failure loud
  // instead of silent.
  server: {
    port:        TAURI_DEV_PORT,
    strictPort:  true,
    host:        "127.0.0.1",
    watch: {
      // Don't trigger HMR on Python/Rust file changes — they're
      // outside the React build.  Tauri itself watches src-tauri/
      // separately; src-python/ is a runtime dep, not a build-time one.
      ignored: ["**/src-python/**", "**/src-tauri/**"],
    },
  },

  // Tauri loads the production build from `dist/`.
  build: {
    target:    "esnext",
    minify:    "esbuild",
    sourcemap: true,
    outDir:    "dist",
    emptyOutDir: true,
  },

  // Path alias `@/` → `src/` for clean imports inside the frontend.
  // Matches the convention shadcn/ui uses; without this, shadcn's
  // generated components break on import.
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },

  // Make import.meta.env.MODE / DEV / PROD work as expected.
  // Vite handles this automatically; no extra config needed.

  // Dev-mode environment variables (prefixed with VITE_) are injected
  // into import.meta.env.  We don't use any yet; backend port comes
  // via the discovery file (see src/lib/api.ts).
})
