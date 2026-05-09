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
    getBackendUrl()
      .then((u) => {
        if (!cancelled) setUrl(u)
      })
      .catch(() => {
        // Connection error is surfaced by useBackend's status pill
        // already; the URL just stays null here.  Components fall
        // back to their loading placeholder.
      })
    return () => { cancelled = true }
  }, [])

  return url
}
