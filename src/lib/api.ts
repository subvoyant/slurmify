// ──────────────────────────────────────────────────────────────────────
// src/lib/api.ts — Backend connection helpers
// ──────────────────────────────────────────────────────────────────────
//
// One-stop module for talking to the Python FastAPI sidecar.  Provides:
//
//   • readBackendDiscovery()  — invokes the Rust command that reads the
//                               discovery file (port + version + pid).
//   • probeHealth(port)       — HTTP GET /health to confirm the backend
//                               is actually answering, not a stale file.
//   • api(path, init?)        — fetch wrapper that prepends the resolved
//                               backend URL.  Caches the URL after first
//                               successful resolve.
//
// All calls return typed values; errors throw.  Components are expected
// to wrap calls in their own error-handling (toasts, banners, etc.).
// ──────────────────────────────────────────────────────────────────────

import { invoke } from "@tauri-apps/api/core"

export interface BackendDiscovery {
  port:       number
  pid:        number
  started_at: number
  version:    string
}

/** Read the discovery file written by src-python/server.py. */
export async function readBackendDiscovery(): Promise<BackendDiscovery> {
  return invoke<BackendDiscovery>("read_backend_discovery")
}

/** Probe /health to confirm the backend is alive at the given port. */
export async function probeHealth(port: number): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, {
      method: "GET",
      // Short timeout — the backend is local; if it doesn't answer
      // in 1.5s something is wrong.  AbortController is the only
      // way fetch() takes a timeout.
      signal: AbortSignal.timeout(1500),
    })
    if (!res.ok) return false
    const body = await res.json() as { ready?: boolean }
    return body.ready === true
  } catch {
    return false
  }
}

/** Read the full /health payload — including the session tmp_dir path
 *  the backend exposes for the "📁 reveal temp files" button. */
export interface HealthInfo {
  status:  string
  version: string
  ready:   boolean
  tmp_dir: string
}

export async function getHealth(): Promise<HealthInfo> {
  return api<HealthInfo>("/health")
}

// ── Cached backend URL ─────────────────────────────────────────────────
// Once we've confirmed the backend, every other API call reuses this
// without re-reading the discovery file.  If the backend dies and
// restarts on a different port, the user has to reload the app —
// acceptable for v0.2.0 (this is a desktop app, not a long-lived
// service that needs hot-reconnect logic).

let _cachedBackendUrl: string | null = null

/** Resolve the backend URL, with auto-recovery if the cached URL is
 *  stale (e.g., backend was restarted on a new port).
 *
 *  Flow:
 *    1. If we have a cached URL, do a quick /health probe.  If the
 *       probe succeeds, return it (the common fast path).
 *    2. Otherwise (no cache OR cached port is dead): read the
 *       discovery file the running backend rewrote at startup,
 *       probe its port, cache it.
 *    3. If both fail, throw.
 *
 *  This means restarting the Python backend in another terminal
 *  "just works" — the next API call notices the dead URL and silently
 *  re-resolves.  No need to reload the Tauri window. */
export async function getBackendUrl(): Promise<string> {
  // Step 1: cached URL still alive?
  if (_cachedBackendUrl) {
    const cachedPort = parseInt(_cachedBackendUrl.split(":").pop() ?? "0", 10)
    if (cachedPort > 0 && (await probeHealth(cachedPort))) {
      return _cachedBackendUrl
    }
    // Cached URL is dead — drop it and fall through to re-resolve.
    _cachedBackendUrl = null
  }

  // Step 2: re-resolve from the discovery file (which the running
  // backend rewrites at startup with its new port).
  const info = await readBackendDiscovery()
  const url = `http://127.0.0.1:${info.port}`
  const ok = await probeHealth(info.port)
  if (!ok) {
    throw new Error(
      `discovery file points to port ${info.port} but /health didn't respond — ` +
      `is the backend still running?`,
    )
  }
  _cachedBackendUrl = url
  return url
}

/** Force a re-resolve next call.  Useful after a "Restart backend"
 *  button (future) or if the user reports a connection error. */
export function invalidateBackendUrl(): void {
  _cachedBackendUrl = null
}

/** Generic fetch wrapper.  Prepends the backend URL and JSON-decodes
 *  the response.  Throws on non-2xx with the body as the error text. */
export async function api<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const base = await getBackendUrl()
  const res = await fetch(`${base}${path}`, init)
  if (!res.ok) {
    const detail = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${detail}`)
  }
  // Some endpoints (file downloads) return non-JSON.  We let those
  // callers use `fetch` directly via getBackendUrl().
  return res.json() as Promise<T>
}
