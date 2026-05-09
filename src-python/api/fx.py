"""
src-python/api/fx.py — FX burn endpoint
─────────────────────────────────────────────────────────────────────

Applies the full FX chain (distortion → ring mod → delay → phaser) to
an existing audio file and writes the result to a new file.  This is
the Python side of the "burn FX" action — the React FX preview chain
runs entirely in the browser via the Web Audio API, but for export
the user wants the FX baked into the file.

Direct port of v0.1.6's burn_fx() in slurm_ui.py.  The DSP itself lives
in slurmcore.apply_fx — UNCHANGED from v0.1.6.

Like /slurmify, this endpoint runs the DSP in a background thread and
exposes progress via the same /jobs/{id}/progress SSE stream from
api/slurmify.py.  Reusing JOBS is intentional: from the frontend's
perspective, "burn FX" is the same kind of job as "slurmify" — just
a different operation.
"""

from __future__ import annotations

import threading
import uuid

import librosa
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import slurmcore
import slurmio

from api.files import register_file, resolve_file
from jobs import JOBS, Job, prune_expired

router = APIRouter(tags=["fx"])


class BurnFxRequest(BaseModel):
    """Parameters for /burn-fx — must match the React FxStore's params shape."""

    file_id:     str = Field(..., description="The file_id of the audio to burn FX onto.")

    # ── FX chain params (defaults match v0.1.6 slider defaults) ────────
    dist_drive:  float = 0.0      # waveshaper drive 0–1
    ring_freq:   float = 200.0    # ring mod carrier Hz
    ring_depth:  float = 0.0      # ring mod depth 0–1
    delay_sec:   float = 0.3      # delay time in seconds
    delay_fb:    float = 0.35     # delay feedback 0–0.9
    delay_mix:   float = 0.0      # delay wet/dry 0–1
    phase_rate:  float = 1.0      # phaser LFO rate Hz
    phase_depth: float = 0.0      # phaser depth 0–1

    # ── Output ─────────────────────────────────────────────────────────
    output_format: str = "wav"


@router.post("/burn-fx")
def start_burn_fx(req: BurnFxRequest):
    """Kick off a burn-fx job and return its job_id immediately.

    Same job-and-SSE pattern as /slurmify; subscribe to
    /jobs/{job_id}/progress for updates.
    """
    src_path = resolve_file(req.file_id)
    if src_path is None:
        raise HTTPException(status_code=404, detail=f"unknown file_id: {req.file_id}")

    prune_expired()

    job = Job(id=str(uuid.uuid4()))
    JOBS[job.id] = job

    threading.Thread(
        target=_run_burn_fx_blocking,
        args=(job, req, src_path),
        daemon=True,
        name=f"burnfx-{job.id[:8]}",
    ).start()

    return {"job_id": job.id}


def _run_burn_fx_blocking(job: Job, req: BurnFxRequest, src_path: str) -> None:
    """Mirror of v0.1.6's burn_fx() with progress reporting.

    The original burn_fx in slurm_ui.py was synchronous and didn't
    report progress — the user clicked Burn and waited.  For v0.2.0
    we add staged progress updates because long stereo files with the
    delay chain can take 10+ seconds.

    Stage timings (approximate):
      0.00 → 0.10  load + shape promotion
      0.10 → 0.30  apply_fx running (the bulk of the time)
      0.95 → 1.00  write to disk
    """
    def _set(p: float, d: str = "") -> None:
        job.progress = p
        job.desc     = d

    try:
        _set(0.05, "Loading audio…")

        # Load with mono=False so stereo files keep their channel layout.
        # Preserve the original sample rate (sr=None) — apply_fx uses it
        # for the ring mod oscillator and the delay buffer length.
        y, sr = librosa.load(src_path, sr=None, mono=False)

        # Promote 1-D mono to (1, n) so the _fx_* functions can treat
        # everything uniformly as (channels, n).  This matches the
        # v0.1.6 burn_fx pattern.
        was_mono = (y.ndim == 1)
        if was_mono:
            y = y[np.newaxis, :]
        y = y.astype(np.float32)

        _set(0.10, "Applying distortion…")
        # apply_fx runs the full chain; it doesn't take a progress
        # callback, but we know roughly how long it takes proportionally
        # to the four stages.  Bump progress between calls would require
        # splitting apply_fx — for v0.2.0 we leave it as one bump at
        # the end of the chain.

        y, sr = slurmcore.apply_fx(
            y, sr,
            dist_drive  = req.dist_drive,
            ring_freq   = req.ring_freq,
            ring_depth  = req.ring_depth,
            delay_sec   = req.delay_sec,
            delay_fb    = req.delay_fb,
            delay_mix   = req.delay_mix,
            phase_rate  = req.phase_rate,
            phase_depth = req.phase_depth,
        )
        _set(0.85, "FX chain complete")

        # Convert back to soundfile's expected layout (ADR-0021):
        #   mono   → shape (n,)
        #   stereo → shape (n, channels)
        # apply_fx returns (channels, n).  Squeeze mono back to 1-D;
        # transpose stereo at the soundfile boundary.
        if was_mono:
            export = y[0]
        elif y.shape[0] == 1:
            # apply_fx may produce shape (1, n) even for 2-D input if
            # all stages happened to be no-ops; squeeze for consistency.
            export = y[0]
        else:
            export = y.T   # (channels, n) → (n, channels) for soundfile

        _set(0.92, "Writing output…")
        out_path = slurmio._write_audio(export, sr, req.output_format)
        output_id = register_file(out_path)
        _set(1.0, "Done ✓")
        job.mark_done(output_id=output_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        job.mark_done(error=f"burn-fx failed: {type(e).__name__}: {e}")
