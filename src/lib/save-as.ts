// ──────────────────────────────────────────────────────────────────────
// src/lib/save-as.ts — Native save-file dialog + download from backend
// ──────────────────────────────────────────────────────────────────────
//
// Without this helper, Slurmify outputs only live in the session temp
// dir — they're purged at app quit (per ADR-0011 + the SIGTERM handler
// in server.py).  This helper bridges that gap: the user picks a
// destination via a real macOS save dialog, we fetch the file from
// the backend and stream it to the chosen path.
//
// Why fetch + write rather than letting the user "right-click → save"
// in the WaveformPlayer?  The Tauri webview's native context menu
// doesn't surface a save action, and our outputs are served from
// localhost over HTTP (not as data: URLs that would bypass the issue).
// A controlled dialog gives us:
//   • Suggested filename (driven by the file_id + format)
//   • Filter for the right extension
//   • Predictable error reporting
//
// Implementation notes:
//   • @tauri-apps/plugin-dialog provides save() — a wrapper around
//     NSSavePanel on macOS.  Returns the chosen path or null on cancel.
//   • @tauri-apps/plugin-fs provides writeFile(path, Uint8Array).
//     Permissions in src-tauri/capabilities/default.json already grant
//     dialog:default + fs:default which cover both APIs.
//   • The backend's /files/{id} endpoint serves with HTTP range
//     support; for a single-shot full download we use a plain fetch.
//     For very large videos this materialises the full file in memory
//     once — acceptable up to ~hundreds of MB; large enough to need
//     streaming would require a Rust-side download command.
// ──────────────────────────────────────────────────────────────────────

import { save } from "@tauri-apps/plugin-dialog"
import { writeFile } from "@tauri-apps/plugin-fs"
import { getBackendUrl } from "@/lib/api"

export interface SaveAsOptions {
  /** The backend-side file_id to download.  Resolves to
   *  /files/{file_id} on the running Slurmify backend. */
  fileId: string
  /** Pre-filled filename in the save dialog.  Should include an
   *  extension matching the audio format (e.g. "siena_slurm.wav"). */
  defaultFilename: string
  /** Display name for the dialog's "Save As" title bar — e.g.
   *  "Save Slurm Output", "Save Burned FX". */
  dialogTitle?: string
  /** File-type filter.  At least one entry recommended so the user
   *  sees a nice "MP3 audio" label rather than a generic "All files". */
  filters?: Array<{ name: string; extensions: string[] }>
}

export type SaveAsResult =
  | { kind: "saved";     path: string }
  | { kind: "cancelled" }
  | { kind: "error";     message: string }

/**
 * Open a native save dialog, download the backend file, write it to
 * the chosen path.  Returns a tagged result so callers can distinguish
 * "user cancelled" from "everything broke" — both are common and the
 * UI should display them differently (cancel = silent; error = toast).
 */
export async function saveBackendFileAs(
  opts: SaveAsOptions,
): Promise<SaveAsResult> {
  // Step 1: ask the user where to put it.
  let chosenPath: string | null
  try {
    chosenPath = await save({
      title:        opts.dialogTitle ?? "Save",
      defaultPath:  opts.defaultFilename,
      filters:      opts.filters,
    })
  } catch (e) {
    return { kind: "error", message: `dialog failed: ${(e as Error).message}` }
  }
  if (chosenPath === null || chosenPath === undefined) {
    return { kind: "cancelled" }
  }

  // Step 2: download the file from the backend.
  let bytes: Uint8Array
  try {
    const baseUrl = await getBackendUrl()
    const res = await fetch(`${baseUrl}/files/${opts.fileId}`)
    if (!res.ok) {
      return {
        kind:    "error",
        message: `backend returned ${res.status} ${res.statusText}`,
      }
    }
    bytes = new Uint8Array(await res.arrayBuffer())
  } catch (e) {
    return {
      kind:    "error",
      message: `download failed: ${(e as Error).message}`,
    }
  }

  // Step 3: write it to disk.
  try {
    await writeFile(chosenPath, bytes)
  } catch (e) {
    return {
      kind:    "error",
      message: `write failed: ${(e as Error).message}`,
    }
  }

  return { kind: "saved", path: chosenPath }
}

/**
 * Common audio-format filter generator.  Use to keep dialog filters
 * consistent across the slurm-output / burn-fx / future export points.
 */
export function audioFilter(format: string): Array<{ name: string; extensions: string[] }> {
  const fmt = format.toLowerCase()
  const labels: Record<string, string> = {
    wav:  "WAV audio",
    mp3:  "MP3 audio",
    flac: "FLAC audio",
    ogg:  "OGG Vorbis audio",
    aiff: "AIFF audio",
    aac:  "AAC audio",
    m4a:  "AAC audio",
  }
  return [{ name: labels[fmt] ?? fmt.toUpperCase(), extensions: [fmt] }]
}

/** Filter for the YouTube-ready MP4 video export. */
export function mp4Filter(): Array<{ name: string; extensions: string[] }> {
  return [{ name: "MP4 video", extensions: ["mp4"] }]
}
