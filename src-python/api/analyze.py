"""
src-python/api/analyze.py — Per-file audio analysis (BPM + duration)
─────────────────────────────────────────────────────────────────────

Runs librosa beat detection on a previously-uploaded file ONCE and
caches the result.  Provides the frontend with:

  • detected_bpm — used by the live ms ⇄ ♪ note-mode hint so the
    user sees real numbers ("≈ 125 ms @ 128 BPM") instead of the
    fallback ("≈ 125 ms @ 120 BPM") that v0.1.6 used.
  • duration_sec — corroborates the duration probe done at upload
    time (sanity check; same value).

Why a separate endpoint instead of folding into /upload?
  The frontend wants the upload response to land FAST so it can show
  the file caption + waveform within ~200ms.  Beat detection adds
  500-2000ms depending on file length.  Splitting the endpoints lets
  the user see the file load instantly, then the BPM "fills in"
  asynchronously a moment later.

Why cache by file_id?
  librosa beat detection is deterministic for a given input — running
  it twice on the same file yields the same BPM.  No reason to
  re-compute on every frontend hot-reload.  The cache lives in this
  module's process scope (cleared at sidecar exit alongside the
  session temp dir).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import librosa
import numpy as np
from fastapi import APIRouter, HTTPException

import slurmcore
import slurmio

from api.files import resolve_file

router = APIRouter(tags=["analyze"])


# ── Cache ─────────────────────────────────────────────────────────────
# file_id → analysis dict.  Populated lazily on first /analyze call;
# cleared with the rest of the session at backend shutdown.
_ANALYSIS_CACHE: dict[str, dict[str, Any]] = {}

# Per-file analysis is single-threaded (one librosa call at a time
# for a given file_id) but multiple files can analyze concurrently.
# A lock per file_id avoids redundant work when the frontend fires
# /analyze repeatedly during fast UI iteration.
_LOCKS: dict[str, threading.Lock] = {}


def _analyze_blocking(file_id: str, path: str) -> dict[str, Any]:
    """Compute BPM + duration for one file.  Called from a worker
    thread because librosa.beat.beat_track is CPU-bound and blocks
    the event loop otherwise."""

    # Load with the same conventions slurmcore expects (mono mixdown
    # for tempo detection, original sample rate via TARGET_SR).
    y, sr = slurmio.load_audio(path)
    y_mono = slurmcore._to_mono(y)
    n_samples = slurmcore._n_samples(y)
    duration_sec = float(n_samples) / float(sr)

    # Beat tracking — the same call detect_slice_points uses internally.
    # No bpm_override hint here; we want the unbiased estimate.
    bpm: float | None = None
    try:
        tempo, _beats = librosa.beat.beat_track(y=y_mono, sr=sr, trim=False)
        # tempo can be a 0-d or 1-d ndarray depending on librosa version.
        bpm_value = float(np.atleast_1d(tempo)[0])
        if bpm_value > 0:
            bpm = bpm_value
    except Exception:
        # Pathological inputs (silence, very short files) make
        # beat_track raise.  Return null bpm; the frontend falls
        # back to the bpm_override or the 120 default.
        bpm = None

    return {
        "file_id":      file_id,
        "duration_sec": duration_sec,
        "channels":     1 if y.ndim == 1 else int(y.shape[0]),
        "sample_rate":  int(sr),
        "bpm":          bpm,
    }


@router.get("/analyze/{file_id}")
async def analyze(file_id: str) -> dict[str, Any]:
    """Return cached analysis for a file_id; compute on first call.

    The first call for a given file_id takes ~1-2s (librosa).
    Subsequent calls return instantly from the cache.

    The `bpm` field can be null if beat_track failed (silence,
    very short audio) — the frontend treats null as "no estimate
    available" and falls back to bpm_override or the 120 default.
    """
    # Fast path: already cached.
    cached = _ANALYSIS_CACHE.get(file_id)
    if cached is not None:
        return cached

    # Validate file_id BEFORE acquiring a lock so a typo returns 404
    # instantly rather than after waiting for an unrelated file's
    # analysis to finish.
    path = resolve_file(file_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown file_id: {file_id}")

    # Acquire the per-file lock so concurrent /analyze calls collapse
    # into one librosa run.  A second caller waits for the first to
    # finish, then reads the cache below.
    lock = _LOCKS.setdefault(file_id, threading.Lock())
    # asyncio-friendly lock acquire — runs the blocking acquire in
    # a worker thread so we don't stall the event loop while waiting.
    await asyncio.to_thread(lock.acquire)
    try:
        # Re-check the cache — the concurrent caller we waited on
        # may have populated it.
        cached = _ANALYSIS_CACHE.get(file_id)
        if cached is not None:
            return cached

        # Run the actual analysis in a worker thread (CPU-bound).
        result = await asyncio.to_thread(_analyze_blocking, file_id, path)
        _ANALYSIS_CACHE[file_id] = result
        return result
    finally:
        lock.release()
