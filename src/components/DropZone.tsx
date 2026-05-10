// ──────────────────────────────────────────────────────────────────────
// src/components/DropZone.tsx — File ingest UI for the INPUT rack module
// ──────────────────────────────────────────────────────────────────────
//
// Two interaction modes (per UI_DESIGN_BRIEF.md §7 deviation):
//   1. Drag-and-drop a file onto the dashed-border target.
//   2. Click the target to open a native file picker.
//
// Either mode POSTs the file to /upload and stores the resulting
// SourceFile in slurmStore.  The component shows three states:
//
//   • idle      — dashed-border target with prompt text + icon
//   • uploading — solid-border target with a thin progress bar
//   • error     — red-border target with the error message
//
// ART-EXTENSION POINTS (for later, when custom artwork is ready):
//   • The dashed-border <div> is the "drop frame" — replace with a
//     painted texture by swapping the className for a bg-image div.
//   • The lucide <Upload> icon at center is a pure SVG; replaceable.
//   • Progress bar is a flat <div>; can be a textured strip.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Upload } from "lucide-react"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { useSlurmStore, type SourceFile } from "@/stores/slurmStore"
import { getBackendUrl } from "@/lib/api"

type DropState =
  | { kind: "idle" }
  | { kind: "uploading"; progress: number; filename: string }
  | { kind: "error"; message: string }

export function DropZone() {
  const setSourceFile = useSlurmStore(s => s.setSourceFile)

  const [state, setState] = React.useState<DropState>({ kind: "idle" })
  const [isDragOver, setIsDragOver] = React.useState(false)

  // Hidden <input type="file"> trigger — clicking the drop region
  // opens the native picker.  Stored in a ref so we can call .click()
  // on the actual element, not a re-render shadow.
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)

  // ── Upload action (shared by drop + click flows) ─────────────────
  //
  // History note: the original implementation rejected with terse
  // strings ("/upload network error") and the catch block fell back to
  // a literal "upload failed" if `e.message` was empty.  In practice
  // the production DMG hit the empty-message path on every drop, so
  // the user saw "upload failed / upload failed / click to retry" —
  // two stacked copies of the fallback string with zero diagnostic
  // value.  This rewrite makes every reject path carry a concrete
  // message AND logs to console.error so even in builds without
  // DevTools the next failure leaves a sidecar log trail.
  const upload = React.useCallback(async (file: File) => {
    setState({ kind: "uploading", progress: 0, filename: file.name })

    let baseUrl = ""
    try {
      // ── Step 1 — resolve the backend URL ─────────────────────────
      // If this throws we want a "backend offline" style message, not
      // a generic "upload failed".  getBackendUrl() throws Error with
      // a useful message already; we just re-wrap to add context.
      try {
        baseUrl = await getBackendUrl()
      } catch (e) {
        const msg = (e as Error)?.message ?? String(e)
        throw new Error(`backend unreachable: ${msg}`)
      }

      // ── Step 2 — POST the file via XHR (for upload-progress) ─────
      // We use XMLHttpRequest (rather than fetch) so we can wire a
      // real upload progress bar.  fetch's body streams don't expose
      // upload progress in any browser yet — XHR is still the only
      // way in 2026.
      const result = await new Promise<SourceFile>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        try {
          xhr.open("POST", `${baseUrl}/upload`)
        } catch (openErr) {
          // xhr.open() throws synchronously on bad URLs, security
          // errors, or unsupported schemes.  Without this catch the
          // exception escapes the Promise executor and the reject
          // path never runs — the outer catch sees the raw thrown
          // value, which in some WebKit builds is a DOMException
          // with empty .message.
          reject(new Error(
            `xhr.open failed for ${baseUrl}/upload: ${
              (openErr as Error)?.message || openErr?.toString() || "unknown error"
            }`
          ))
          return
        }

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            setState({
              kind: "uploading",
              progress: e.loaded / e.total,
              filename: file.name,
            })
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText))
            } catch (e) {
              reject(new Error(
                `bad JSON in /upload response (status ${xhr.status}): ` +
                `${(e as Error)?.message || e} — body starts with: ` +
                xhr.responseText.slice(0, 120),
              ))
            }
          } else {
            // Status 0 means "request never reached the server" —
            // CORS rejection, mixed-content block, network drop, etc.
            // Spell that out so the failure mode is obvious from the
            // UI alone.
            const friendly = xhr.status === 0
              ? "request blocked or aborted before reaching the server (status 0 — CORS, mixed-content, or network drop)"
              : `/upload returned ${xhr.status} ${xhr.statusText || ""}: ${xhr.responseText.slice(0, 200)}`
            reject(new Error(friendly))
          }
        }
        xhr.onerror = () => {
          // The Event passed to onerror is intentionally information-
          // free per the XHR spec.  Surface what we DO know — readyState,
          // status, statusText — so the user can tell whether the
          // request even left the WebView.
          reject(new Error(
            `/upload network error (readyState=${xhr.readyState}, ` +
            `status=${xhr.status}, statusText="${xhr.statusText}"). ` +
            "Common causes on a Tauri build: CORS, mixed content, or " +
            "the sidecar restarted on a new port.",
          ))
        }
        xhr.onabort = () => reject(new Error(
          `/upload aborted (readyState=${xhr.readyState}, status=${xhr.status})`,
        ))
        xhr.ontimeout = () => reject(new Error(
          `/upload timed out (readyState=${xhr.readyState})`,
        ))

        try {
          const formData = new FormData()
          formData.append("file", file, file.name)
          xhr.send(formData)
        } catch (sendErr) {
          // Same defensive wrap as xhr.open — synchronous throws from
          // xhr.send aren't unheard of in WebKit (e.g., sandbox
          // violations) and would otherwise propagate out as the
          // raw value.
          reject(new Error(
            `xhr.send failed: ${
              (sendErr as Error)?.message || sendErr?.toString() || "unknown error"
            }`,
          ))
        }
      })

      // Success — drop the SourceFile into the store, which causes
      // App.tsx's SourcePanel to swap from <DropZone> to the loaded
      // file caption + (Phase D2) waveform.
      setSourceFile(result)
      setState({ kind: "idle" })
    } catch (e) {
      // Belt-and-braces: even if a non-Error sneaks through, produce a
      // human-readable message instead of falling back to a literal
      // "upload failed" placeholder.
      const err = e as Error | undefined
      const msg =
        (err && err.message) ||
        (e && typeof e === "object" && "toString" in e ? e.toString() : "") ||
        (typeof e === "string" ? e : "") ||
        "unknown error (no message on thrown value)"
      console.error("[DropZone] upload failed:", e, "→", msg)
      setState({ kind: "error", message: msg })
    }
  }, [setSourceFile])

  // ── Drag-and-drop handlers ───────────────────────────────────────
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()        // required to allow drop
    setIsDragOver(true)
  }
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void upload(file)
  }

  // ── Click handler — open native picker ───────────────────────────
  const onClickTarget = () => fileInputRef.current?.click()

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) void upload(file)
    // Reset the input so re-selecting the SAME file fires onChange again.
    e.target.value = ""
  }

  // ── Render ────────────────────────────────────────────────────────
  // Three states drive different visuals.  All three share the same
  // outer dashed-border target so layout doesn't jump between states.
  const isError      = state.kind === "error"
  const isUploading  = state.kind === "uploading"

  return (
    <div className="flex items-stretch gap-3">
      {/* The drop target — square-ish, fixed-size on the left.  The
          dashed border is intentional (UI_DESIGN_BRIEF §7 lists drag
          targets as a legitimate deviation from the "no per-control
          borders" rule).

          Layout rule: idle + uploading are h-24 fixed; error grows
          vertically (min-h-24 + h-auto) so longer diagnostic messages
          have room to wrap.  This matters now that the error message
          carries actionable detail like XHR readyState/status — a
          fixed h-24 would clip the message off-screen and we'd be
          back to the original "two stacked 'upload failed' lines"
          mystery. */}
      <Tip
        text={
          <>
            Drop or click to load any audio (wav, mp3, flac, m4a, ogg,
            aiff) or video file (mp4, mov, mkv, webm, avi). Video
            files have their audio extracted via ffmpeg and converted
            to 44.1 kHz stereo WAV. Mono and stereo are both
            preserved end-to-end through the slurmify pipeline.
          </>
        }
      >
        <button
          type="button"
          onClick={onClickTarget}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={cn(
            "flex w-64 shrink-0 flex-col items-center justify-center gap-1.5",
            // Height policy: idle/uploading stay compact; error
            // expands so the diagnostic message is readable.
            isError ? "min-h-24 h-auto py-2" : "h-24",
            "rounded border-2 border-dashed",
            "transition-colors",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slurm-cyan",
            // State-driven border + bg
            isError      && "border-slurm-danger bg-slurm-danger/5 text-slurm-danger",
            isUploading  && "border-solid border-slurm-cyan bg-slurm-cyan/5",
            !isError && !isUploading &&
              (isDragOver
                ? "border-slurm-cyan bg-slurm-cyan/5 text-slurm-cyan"
                : "border-slurm-border-2 hover:border-slurm-cyan hover:bg-slurm-surface2 text-slurm-muted"),
          )}
        >
        {state.kind === "idle" && (
          <>
            <Upload className="h-5 w-5" />
            <span className="text-[11px] font-medium">drop audio or video</span>
            <span className="text-[10px] opacity-70">or click to browse</span>
          </>
        )}
        {state.kind === "uploading" && (
          <>
            <span className="text-[11px] font-medium text-slurm-cyan">
              uploading {state.filename}…
            </span>
            <div className="mt-1 h-1 w-3/4 overflow-hidden rounded bg-slurm-border">
              <div
                className="h-full bg-slurm-cyan transition-[width] duration-150"
                style={{ width: `${Math.round(state.progress * 100)}%` }}
              />
            </div>
            <span className="text-[10px] tabular-nums text-slurm-muted">
              {Math.round(state.progress * 100)}%
            </span>
          </>
        )}
        {state.kind === "error" && (
          <>
            <span className="text-[11px] font-medium">upload failed</span>
            {/* break-words + leading-tight + max-w-full so a long
                XHR diagnostic message wraps inside the box rather
                than overflowing to the right.  whitespace-normal
                is also explicit — buttons have whitespace-nowrap
                in some shadcn/ui resets, which would re-introduce
                the "single ellipsised line" failure mode. */}
            <span className="px-2 text-[10px] leading-tight opacity-90 break-words whitespace-normal max-w-full text-center">
              {state.message}
            </span>
            <span className="text-[10px] underline">click to retry</span>
          </>
        )}
        </button>
      </Tip>

      {/* Hidden file picker — triggered by clicking the target above.
          file_types matches what the backend accepts (audio + video). */}
      <input
        ref={fileInputRef}
        type="file"
        accept="audio/*,video/*,.wav,.mp3,.flac,.m4a,.ogg,.aac,.aiff,.mp4,.mov,.mkv,.webm,.avi,.wmv,.flv"
        onChange={onFileChange}
        className="hidden"
      />

      {/* Right column — helper text describing accepted formats.
          When real artwork lands later, this column is a good slot
          for a small illustration / hint pixel. */}
      <div className="flex flex-1 flex-col justify-center gap-1 text-[11px] text-slurm-muted">
        <div>
          <span className="text-slurm-fg">accepted:</span> wav · mp3 · flac · m4a · ogg · aiff
        </div>
        <div>
          <span className="text-slurm-fg">video:</span> mp4 · mov · mkv · webm · avi (audio extracted via ffmpeg)
        </div>
        <div className="opacity-70">
          stereo + mono are both preserved end-to-end
        </div>
      </div>
    </div>
  )
}
