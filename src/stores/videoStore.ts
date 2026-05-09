// ──────────────────────────────────────────────────────────────────────
// src/stores/videoStore.ts — Video render params + job state
// ──────────────────────────────────────────────────────────────────────
//
// Tracks the render-video flow: title/creator metadata + the in-flight
// render job.  Mirror of the slurm/fx job-state slices but for the
// /render-video endpoint.
//
// The metadata fields persist (the user's last title/creator survive
// reloads), but the rendered file_id does NOT — like all backend
// outputs, it points at a session-temp file that's gone after a
// sidecar restart.
// ──────────────────────────────────────────────────────────────────────

import { create } from "zustand"
import { persist } from "zustand/middleware"

export interface VideoMetadata {
  /** Free-form title for the video.  Embedded into the MP4 metadata
   *  atom AND used in the safe-title portion of the output filename.
   *  Empty = backend defaults to "Subvoyant Slurm <jumble>". */
  title: string
  /** Creator/artist name.  Embedded into the MP4 artist atom.
   *  Empty = "Subvoyant SIENA Slurmer" default on the backend. */
  creator: string
  /** When true, the original input filename is referenced in the
   *  PATCH JSON metadata blob (ADR-0008).  Off by default because
   *  some users prefer not to leak source-file names. */
  includeSourceFilename: boolean
}

export const defaultVideoMetadata = (): VideoMetadata => ({
  title:                 "",
  creator:               "",
  includeSourceFilename: false,
})

interface VideoJobState {
  jobId:        string | null
  progress:     number
  desc:         string
  isRunning:    boolean
  error:        string | null
  /** file_id of the rendered MP4.  When set, the VIDEO module shows
   *  a preview <video> + the save-as button. */
  renderedFileId: string | null
}

const initialJobState: VideoJobState = {
  jobId:          null,
  progress:       0,
  desc:           "",
  isRunning:      false,
  error:          null,
  renderedFileId: null,
}

interface VideoStore extends VideoJobState {
  metadata: VideoMetadata

  // ── Metadata actions ─────────────────────────────────────────────
  setMetadata: <K extends keyof VideoMetadata>(key: K, value: VideoMetadata[K]) => void
  resetMetadata: () => void

  // ── Job lifecycle (used by useRenderVideoJob) ────────────────────
  startRender:  (jobId: string) => void
  updateRender: (p: { progress: number; desc: string }) => void
  finishRender: (renderedFileId: string | null, error: string | null) => void
  /** Drop the rendered preview — useful if the user wants to redo
   *  with different metadata without keeping the previous result. */
  clearRender:  () => void
}

export const useVideoStore = create<VideoStore>()(
  persist(
    (set) => ({
      metadata: defaultVideoMetadata(),
      ...initialJobState,

      setMetadata: (key, value) =>
        set((s) => ({ metadata: { ...s.metadata, [key]: value } })),

      resetMetadata: () => set({ metadata: defaultVideoMetadata() }),

      startRender: (jobId) => set({
        jobId,
        progress:  0,
        desc:      "",
        isRunning: true,
        error:     null,
      }),

      updateRender: ({ progress, desc }) => set({ progress, desc }),

      finishRender: (renderedFileId, error) => set({
        renderedFileId,
        error,
        isRunning: false,
        progress:  renderedFileId ? 1 : 0,
      }),

      clearRender: () => set(initialJobState),
    }),
    {
      name: "slurmify_video_session_v1",
      // Only the user-meaningful metadata survives reloads.  Job
      // state is transient; renderedFileId points at a session-temp
      // file the backend forgets on restart.
      partialize: (s) => ({ metadata: s.metadata }),
    },
  ),
)
