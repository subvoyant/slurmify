// ──────────────────────────────────────────────────────────────────────
// src/hooks/useBackend.ts — Backend connection lifecycle hook
// ──────────────────────────────────────────────────────────────────────
//
// Owns the "is the Python backend running?" question for the entire app.
// Mounts a polling effect that:
//
//   1. Calls Rust's read_backend_discovery to find a running backend.
//   2. Probes /health to confirm the file isn't stale.
//   3. Sets status to `ready` (with port + version) on success.
//   4. Retries every 2s while not ready — handles the case where the
//      user starts the backend AFTER the Tauri window opens.
//
// Status is a discriminated union so consumers can switch on the kind
// without unsafe casts:
//
//   if (status.kind === "ready") {
//     console.log("on port", status.port)
//   }
//
// Once status is `ready`, the polling stops.  If the backend crashes
// later, individual API calls will start failing — the consumer's job
// to surface that via the per-action error UI, not this hook.
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react"
import { readBackendDiscovery, probeHealth } from "../lib/api"

export type BackendStatus =
  | { kind: "checking" }
  | { kind: "ready";   port: number; version: string }
  | { kind: "error";   message: string }

export function useBackend(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>({ kind: "checking" })

  useEffect(() => {
    // `cancelled` guards against state updates after unmount — if the
    // user closes the window while we're mid-fetch, we don't want
    // React to log a "set state on unmounted component" warning.
    let cancelled = false

    const tryConnect = async (): Promise<boolean> => {
      try {
        const info = await readBackendDiscovery()
        const ok   = await probeHealth(info.port)
        if (cancelled) return false
        if (!ok) {
          setStatus({
            kind: "error",
            message:
              `discovery file points to port ${info.port} but /health didn't respond — ` +
              `start the backend with: python src-python/server.py`,
          })
          return false
        }
        setStatus({ kind: "ready", port: info.port, version: info.version })
        return true
      } catch (e) {
        if (cancelled) return false
        // The Rust command returns "not found" specifically when the
        // discovery file doesn't exist — treat that as "still booting"
        // not as a hard error, so the message is friendlier.
        const msg = String((e as { message?: unknown })?.message ?? e)
        if (msg === "not found" || msg.includes("not found")) {
          setStatus({
            kind: "error",
            message: "backend not running — start it with: python src-python/server.py",
          })
        } else {
          setStatus({ kind: "error", message: msg })
        }
        return false
      }
    }

    // First attempt immediately.
    tryConnect()

    // Poll every 2s until ready.  We use a self-clearing interval rather
    // than recursive setTimeout so that React's StrictMode double-mount
    // doesn't accidentally start two interval chains.
    const id = setInterval(async () => {
      // Read latest status synchronously by closing over a ref isn't
      // worth the complexity — the worst case here is one extra
      // tryConnect() call after success, which is harmless (it sets
      // the same `ready` state again).
      const success = await tryConnect()
      if (success) clearInterval(id)
    }, 2000)

    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return status
}
