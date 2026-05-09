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
  const upload = React.useCallback(async (file: File) => {
    setState({ kind: "uploading", progress: 0, filename: file.name })

    try {
      const baseUrl = await getBackendUrl()

      // We use XMLHttpRequest (rather than fetch) so we can wire a
      // real upload progress bar.  fetch's body streams don't expose
      // upload progress in any browser yet — XHR is still the only
      // way in 2026.
      const result = await new Promise<SourceFile>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open("POST", `${baseUrl}/upload`)

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
              reject(new Error(`bad JSON in /upload response: ${e}`))
            }
          } else {
            reject(new Error(`/upload returned ${xhr.status}: ${xhr.responseText}`))
          }
        }
        xhr.onerror = () => reject(new Error("/upload network error"))
        xhr.onabort = () => reject(new Error("/upload aborted"))

        const formData = new FormData()
        formData.append("file", file)
        xhr.send(formData)
      })

      // Success — drop the SourceFile into the store, which causes
      // App.tsx's SourcePanel to swap from <DropZone> to the loaded
      // file caption + (Phase D2) waveform.
      setSourceFile(result)
      setState({ kind: "idle" })
    } catch (e) {
      setState({
        kind: "error",
        message: (e as Error).message || "upload failed",
      })
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
          borders" rule). */}
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
            "flex h-24 w-64 shrink-0 flex-col items-center justify-center gap-1.5",
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
            <span className="px-2 text-[10px] opacity-80">{state.message}</span>
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
