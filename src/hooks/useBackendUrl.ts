// ──────────────────────────────────────────────────────────────────────
// src/hooks/useBackendUrl.ts — Sync access to the resolved backend URL
// ──────────────────────────────────────────────────────────────────────
//
// `getBackendUrl()` in lib/api.ts returns a Promise — fine for one-shot
// calls during user actions, but awkward for building URLs inside a
// component's render (e.g., `<audio src={...}>`).  This hook resolves
// the backend URL once and returns it as plain state.
//
//   const backendUrl = useBackendUrl()
//   // null until resolved; after that, "http://127.0.0.1:NNNNN"
//
//   if (backendUrl) {
//     <audio src={`${backendUrl}/files/${fileId}`} />
//   }
//
// Components are expected to handle the null case (typically by showing
// a small loading placeholder).  Once resolved, the URL is stable for
// the rest of the session — backend restarts on a different port
// require a full app reload (the "reconnect" button).
// ──────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react"
import { getBackendUrl } from "@/lib/api"

export function useBackendUrl(): string | null {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    // Retry-with-backoff loop.  The original implementation called
    // getBackendUrl() exactly once and silently dropped the URL to
    // null forever if the FIRST attempt failed.  In production that
    // breaks every consumer (WaveformPlayer especially) when the
    // backend is briefly busy — e.g., librosa.load on a freshly-
    // uploaded m4a is decoding and /health probes time out.
    //
    // Now we retry every 1.5 s until we get a URL.  Once successful
    // we stop — the resolved URL is cached at module level by
    // getBackendUrl() so subsequent calls are O(1).  If the backend
    // dies later, the user reloads the app (consistent with our
    // "no hot-reconnect" stance from the original lib/api.ts comment).
    const tryResolve = async () => {
      while (!cancelled) {
        try {
          const u = await getBackendUrl()
          if (!cancelled) setUrl(u)
          return
        } catch {
          // Wait before retrying.  1.5 s matches useBackend's poll
          // cadence so two hooks racing the same /health probe
          // don't pile up.
          await new Promise((r) => setTimeout(r, 1500))
        }
      }
    }

    void tryResolve()
    return () => { cancelled = true }
  }, [])

  return url
}
