"""
src-python/api/slurmify.py — Main DSP endpoint
─────────────────────────────────────────────────────────────────────

Hosts the Python side of the user's "slurmify" action: take an uploaded
audio file, apply the slurmify pipeline (slice → stretch → per-slice DSP
→ concat → normalize), and write the result to a new file.

Architecture mirrors the Gradio v0.1.6 process() handler with one big
difference: HTTP request/response can't sit on a 5–30-second blocking
DSP call without timing out, so we kick off the DSP in a background
thread and let the React frontend subscribe to a Server-Sent Events
stream for progress updates.

Flow
────
  1. POST /slurmify with a SlurmifyRequest body                       \
                                              ↓                        \
  2. Create a Job, register it in JOBS, return job_id                  | one HTTP
                                              ↓                        | request
  3. Background thread runs slurmcore.slurmify(),                      | / response
     mutating job.progress as it goes                                  /
                                              ↓
  4. Frontend opens GET /jobs/{job_id}/progress (SSE),                 \
     receives a stream of {progress, desc, done} payloads              | streaming
                                              ↓                        | until done
  5. On done, payload includes output_id; frontend GETs                |
     /files/{output_id} to render the result waveform                  /

Stereo + note-mode + beat-mask behaviours all carry forward from
v0.1.6 unchanged — slurmcore.slurmify is imported as-is.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# Project-root imports (slurmcore + slurmio are at repo root).
import slurmcore
import slurmio

from api.files import register_file, resolve_file
from jobs import JOBS, Job, prune_expired

router = APIRouter(tags=["slurmify"])


# ── Request schema ─────────────────────────────────────────────────────
# Pydantic gives us:
#   • automatic JSON validation on the request body
#   • IDE-friendly typing
#   • a one-to-one mapping with the TypeScript SlurmParams in the React
#     store, so adding a parameter is a 2-file edit (this + the TS type)
#
# Field defaults match the Gradio UI defaults from slurm_ui.py's
# build_ui() so a request that omits a field still produces the expected
# behaviour (nothing happens / sensible no-op).

class SlurmifyRequest(BaseModel):
    file_id: str = Field(..., description="The file_id returned by /upload.")

    # ── Core slicing / stretching params ───────────────────────────────
    speed:                 float = 2.0
    resolution:            str   = "1/16"
    transient_sensitivity: float = 0.5
    envelope_ms:           float = 2.0
    preserve_pitch:        bool  = True
    pitch_shift_semitones: float = 0.0

    # ── Per-slice DSP params ──────────────────────────────────────────
    randomize_order:       bool  = False
    reverse_chance:        float = 0.0
    stutter_chance:        float = 0.0
    stutter_skip_ms:       float = 0.0
    stutter_max_reps:      int   = 0
    stutter_spread:        float = 0.0
    beat_trim_start_ms:    float = 0.0
    beat_trim_end_ms:      float = 0.0
    beat_gap_ms:           float = 0.0

    # ── Note-mode counterparts (ADR-0020) ─────────────────────────────
    # When the user toggles a slider into "♪" mode the frontend sends a
    # note string here (e.g. "1/16", "1/8.", "1/4T") and slurmify converts
    # via _note_to_ms using the BPM detect_slice_points landed on.
    # Empty string = "use the ms value" (full backward compat).
    stutter_skip_note:     str = ""
    beat_trim_start_note:  str = ""
    beat_trim_end_note:    str = ""
    beat_gap_note:         str = ""

    # ── Tempo + range ─────────────────────────────────────────────────
    bpm_override:          float | None = None
    start_sec:             float        = 0.0
    end_sec:               float        = 0.0

    # ── Reproducibility ───────────────────────────────────────────────
    seed:                  int | None = None

    # ── Beat mask (ADR-0019) ──────────────────────────────────────────
    # List of bools, one per beat-position-in-bar.  None or all-True =
    # no masking.  See ADR-0019 in the v0.1.6 codebase.
    beat_mask:             list[bool] | None = None

    # ── Output formatting ─────────────────────────────────────────────
    output_format: str = "wav"


# ── Endpoint: POST /slurmify ───────────────────────────────────────────

@router.post("/slurmify")
def start_slurmify(req: SlurmifyRequest, bg: BackgroundTasks):
    """Kick off a slurmify job and return its job_id immediately.

    The DSP runs in a background thread (slurmify is blocking CPU-bound
    work; Python's GIL releases inside numpy / librosa hot paths so a
    thread is fine).  Progress is reported via a callback that mutates
    the Job record; the SSE endpoint streams those updates.

    Returns
    ──────
    dict
        ```{"job_id": "<uuid4>"}```
    """
    # Validate the source file_id eagerly so the client gets a 404
    # synchronously rather than via the SSE stream.
    src_path = resolve_file(req.file_id)
    if src_path is None:
        raise HTTPException(status_code=404, detail=f"unknown file_id: {req.file_id}")

    # Opportunistic pruning — keeps JOBS small without a periodic task.
    prune_expired()

    job = Job(id=str(uuid.uuid4()))
    JOBS[job.id] = job

    # FastAPI's BackgroundTasks runs after the response is sent.  For DSP
    # we want the thread to start IMMEDIATELY (the client is about to
    # subscribe to SSE and expects progress within 100ms), so we use a
    # plain threading.Thread instead of BackgroundTasks.
    #
    # Why not asyncio.to_thread + bg.add_task?
    #   • bg.add_task waits for the response to flush before scheduling.
    #     With SSE the response is the long-lived stream, so "after the
    #     response" never fires.
    #   • A standalone Thread is the simplest "fire and forget" pattern
    #     that runs concurrently with the SSE generator.
    threading.Thread(
        target=_run_slurmify_blocking,
        args=(job, req, src_path),
        daemon=True,        # don't block process exit
        name=f"slurmify-{job.id[:8]}",
    ).start()

    return {"job_id": job.id}


# ── Background worker ───────────────────────────────────────────────────

def _run_slurmify_blocking(job: Job, req: SlurmifyRequest, src_path: str) -> None:
    """Run slurmcore.slurmify in this thread, updating job.progress as we go.

    All exceptions are caught and stored on job.error; the thread never
    propagates them (would silently kill the worker).  The frontend sees
    them via the SSE payload's `error` field.
    """
    def _progress_cb(frac: float, desc: str = "") -> None:
        # Slurmcore calls this throughout the pipeline.  Atomic field
        # writes — no lock needed.
        job.progress = float(frac)
        job.desc     = str(desc)

    try:
        # Load the source audio.  v0.1.6's load_audio returns either
        # (n,) for mono or (channels, n) for stereo (ADR-0021), and
        # slurmify handles both shapes.
        y, sr = slurmio.load_audio(src_path)

        # Run the DSP pipeline.  This blocks the worker thread for
        # 1–30 seconds depending on file length and params; the SSE
        # endpoint runs concurrently in the asyncio event loop and
        # will see progress updates throughout.
        y_out, sr_out = slurmcore.slurmify(
            y=y, sr=sr,
            speed=req.speed,
            resolution=req.resolution,
            transient_sensitivity=req.transient_sensitivity,
            envelope_ms=req.envelope_ms,
            preserve_pitch=req.preserve_pitch,
            pitch_shift_semitones=req.pitch_shift_semitones,
            randomize_order=req.randomize_order,
            reverse_chance=req.reverse_chance,
            stutter_chance=req.stutter_chance,
            stutter_skip_ms=req.stutter_skip_ms,
            stutter_max_reps=req.stutter_max_reps,
            stutter_spread=req.stutter_spread,
            beat_trim_start_ms=req.beat_trim_start_ms,
            beat_trim_end_ms=req.beat_trim_end_ms,
            beat_gap_ms=req.beat_gap_ms,
            bpm_override=req.bpm_override,
            start_sec=req.start_sec,
            end_sec=req.end_sec,
            seed=req.seed,
            beat_mask=req.beat_mask,
            stutter_skip_note=req.stutter_skip_note,
            beat_trim_start_note=req.beat_trim_start_note,
            beat_trim_end_note=req.beat_trim_end_note,
            beat_gap_note=req.beat_gap_note,
            _progress=_progress_cb,
        )

        # Channel-layout boundary (ADR-0021): slurmify returns
        # (channels, n) for stereo; soundfile + ffmpeg expect (n, channels).
        # 1-D mono passes through unchanged.
        if y_out.ndim == 2:
            y_out = y_out.T

        out_path = slurmio._write_audio(y_out, sr_out, req.output_format)
        output_id = register_file(out_path)
        job.mark_done(output_id=output_id)

    except ValueError as e:
        # slurmcore raises ValueError for user-facing input errors
        # (e.g. trim range invalid, audio too short).  Surface as a
        # friendly error string, not a stack trace.
        job.mark_done(error=str(e))

    except Exception as e:
        # Anything else is unexpected — log full info to stderr for
        # diagnostics, but only show a short message to the user.
        import traceback
        traceback.print_exc()
        job.mark_done(error=f"slurmify failed: {type(e).__name__}: {e}")


# ── Endpoint: GET /jobs/{job_id}/progress (SSE) ────────────────────────

@router.get("/jobs/{job_id}/progress")
async def progress_stream(job_id: str):
    """Server-Sent Events stream of job progress updates.

    The stream emits a JSON payload roughly every 100ms while progress
    is changing, plus a final payload with `done: true` when the job
    completes (success or error).  After the final payload, the stream
    closes — the frontend's EventSource sees `onerror` and stops
    listening.

    Payload shape: see Job.to_dict() in jobs.py.

    Why polling 100ms instead of an event/Condition primitive?
      • slurmcore's _progress callback is synchronous; making it
        asyncio-aware would require threading the event loop through
        the DSP call, which we don't want to touch.
      • 10 Hz is well below human perception of progress-bar smoothness
        and adds negligible CPU.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")

    async def event_generator():
        last: tuple[float, str, bool] = (-1.0, "", False)
        while True:
            cur = (job.progress, job.desc, job.done)
            if cur != last:
                # sse-starlette accepts a dict with a "data" key;
                # the value becomes the `data:` line of the SSE event.
                yield {"data": job.to_json()}
                last = cur
            if job.done:
                break
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())


# ── Endpoint: GET /jobs/{job_id} — polling fallback ────────────────────

@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    """Single-shot job status, useful as a polling fallback if SSE is flaky.

    Same payload as the SSE stream's `data:` line, just delivered as
    a plain JSON response.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    return job.to_dict()
