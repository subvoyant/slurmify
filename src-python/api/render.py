"""
src-python/api/render.py — YouTube-ready MP4 export endpoint
─────────────────────────────────────────────────────────────────────

Renders a 1920×1080 MP4 from the slurm output by stream-copying the
pre-encoded loop animation (assets/siebaSlurm_A003.mp4) and encoding
the audio to AAC.  Direct port of v0.1.6's render_video() in slurm_ui.py.

The video stream is NEVER re-encoded — that's the whole point of the
ADR-0006 stream-copy design (render time is dominated by the audio
encode, not video encoding).  The loop is duplicated as needed to
match the audio duration via ffmpeg's `-stream_loop` flag.

The output MP4 carries a self-describing PATCH JSON blob in its
description metadata atom (ADR-0008), capturing every slurmify and FX
parameter that produced the audio.  This makes the file fully
reproducible — a future "import patch" feature could re-apply the same
settings to a new source.

Same job pattern as /slurmify and /burn-fx; subscribe to
/jobs/{id}/progress for updates.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import slurmio

from api.files import register_file, resolve_file
from jobs import JOBS, Job, prune_expired

router = APIRouter(tags=["render"])

# ── Version (must stay in sync with slurm_ui.__version__) ──────────────
# We can't import from slurm_ui because it's Gradio-dependent and we're
# replacing it.  Instead we read the version from the slurmify.spec file
# at module load time (single source of truth — see version-bump
# checklist in CLAUDE.md).  If reading fails for any reason, fall back
# to "0.2.0" since this module is part of the v0.2.0 codebase.
def _read_version() -> str:
    spec_path = Path(__file__).resolve().parents[2] / "slurmify.spec"
    try:
        for line in spec_path.read_text().splitlines():
            if "CFBundleShortVersionString" in line:
                # line looks like:  "CFBundleShortVersionString": "0.2.0",
                _, _, rest = line.partition(":")
                return rest.strip().strip(",").strip().strip('"')
    except OSError:
        pass
    return "0.2.0"

__version__ = _read_version()


# ── Filename mangling helpers (port from slurm_ui.py) ──────────────────
# These produce the _jumble_name and _safe_title strings that v0.1.6
# baked into MP4 filenames.  We reproduce them here verbatim so users
# moving from v0.1.6 to v0.2.0 see consistent filename patterns.

_LEET_PAIRS = {
    "e": "3", "3": "e",
    "s": "5", "5": "s",
    "o": "0", "0": "o",
    "i": "1", "1": "i",
}


def _leetify(chars: list[str], rng: random.Random, prob: float = 0.5) -> list[str]:
    return [
        _LEET_PAIRS[c] if (c in _LEET_PAIRS and rng.random() < prob) else c
        for c in chars
    ]


def _jumble_name(src_path: str, *, length: int = 16, seed: int | None = None) -> str:
    base = Path(src_path).stem.lower() if src_path else ""
    chars = [c for c in base if c.isalnum()]
    rng = random.Random(seed)
    if chars:
        rng.shuffle(chars)
    pool = "abcdefghijklmnopqrstuvwxyz0123456789"
    while len(chars) < length:
        chars.append(rng.choice(pool))
    chars = chars[:length]
    chars = _leetify(chars, rng)
    return "".join(chars)


def _safe_title(s: str, max_len: int = 40) -> str:
    if not s:
        return ""
    out = []
    for c in s.strip().lower():
        if c.isalnum():
            out.append(c)
        elif c in " -_":
            out.append("_")
    cleaned = "".join(out).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned[:max_len]


# ── Request schema ─────────────────────────────────────────────────────

class RenderVideoRequest(BaseModel):
    """All the params needed to render a YouTube MP4 + bake the PATCH metadata."""

    # ── Audio source ──────────────────────────────────────────────────
    audio_file_id:        str = Field(..., description="file_id of the audio to embed (slurm output or burn-fx output).")
    audio_source_label:   str = "slurm output"   # "slurm output" or "FX-burned output"

    # ── Original input (for filename + optional metadata) ─────────────
    src_input_file_id:    str | None = None
    include_source_filename: bool   = False

    # ── Video metadata ────────────────────────────────────────────────
    title_text:           str = ""
    creator_text:         str = ""

    # ── Slurmify params (all of these go into the PATCH JSON blob) ────
    speed:                 float | None = None
    resolution:            str | None   = None
    transient_sensitivity: float | None = None
    envelope_ms:           float | None = None
    preserve_pitch:        bool | None  = None
    pitch_shift_semitones: float        = 0.0
    randomize_order:       bool         = False
    reverse_chance:        float        = 0.0
    stutter_chance:        float        = 0.0
    stutter_skip_ms:       float        = 0.0
    stutter_max_reps:      int          = 4
    stutter_spread:        float        = 0.0
    beat_trim_start_ms:    float        = 0.0
    beat_trim_end_ms:      float        = 0.0
    beat_gap_ms:           float        = 0.0
    bpm_override:          float | None = None
    seed:                  int | None   = None
    beat_mask:             list[bool] | None = None

    # ── Note-mode (mode, note) pairs (ADR-0020) ───────────────────────
    stutter_skip_mode:     str = "ms"
    stutter_skip_note:     str = ""
    beat_trim_start_mode:  str = "ms"
    beat_trim_start_note:  str = ""
    beat_trim_end_mode:    str = "ms"
    beat_trim_end_note:    str = ""
    beat_gap_mode:         str = "ms"
    beat_gap_note:         str = ""

    # ── FX chain params (also baked into PATCH) ───────────────────────
    dist_drive:  float = 0.0
    ring_freq:   float = 200.0
    ring_depth:  float = 0.0
    delay_time:  float = 0.3
    delay_fb:    float = 0.35
    delay_mix:   float = 0.0
    phase_rate:  float = 1.0
    phase_depth: float = 0.0


@router.post("/render-video")
def start_render_video(req: RenderVideoRequest):
    """Kick off a video-render job and return its job_id immediately."""
    audio_path = resolve_file(req.audio_file_id)
    if audio_path is None:
        raise HTTPException(status_code=404, detail=f"unknown audio file_id: {req.audio_file_id}")

    src_input_path = (
        resolve_file(req.src_input_file_id) if req.src_input_file_id else None
    )

    prune_expired()

    job = Job(id=str(uuid.uuid4()))
    JOBS[job.id] = job

    threading.Thread(
        target=_run_render_blocking,
        args=(job, req, audio_path, src_input_path),
        daemon=True,
        name=f"render-{job.id[:8]}",
    ).start()

    return {"job_id": job.id}


def _run_render_blocking(
    job: Job,
    req: RenderVideoRequest,
    audio_path: str,
    src_input_path: str | None,
) -> None:
    """Direct port of render_video() from v0.1.6 slurm_ui.py.

    Major steps:
      1. Locate the pre-encoded loop MP4.
      2. Build the PATCH JSON blob with all slurmify + FX params.
      3. Build the output filename (_safe_title + _jumble_name).
      4. Build MP4 metadata atoms (title / artist / album / description).
      5. Run ffmpeg with -stream_loop on the video, AAC encode the audio,
         write metadata via -metadata flags, +faststart for streaming.
      6. Register the output and finish the job.
    """
    def _set(p: float, d: str = "") -> None:
        job.progress = p
        job.desc     = d

    try:
        _set(0.05, "Locating loop animation…")

        # Step 1 — find the pre-encoded loop MP4.
        loop_path = slurmio._asset("assets/siebaSlurm_A003.mp4")
        if not os.path.isfile(loop_path):
            raise FileNotFoundError(
                "Missing animation loop — assets/siebaSlurm_A003.mp4 not found."
            )

        # Step 2 — build the PATCH JSON blob (ADR-0008).
        _set(0.10, "Building patch metadata…")
        patch: dict[str, Any] = {
            "version": __version__,
            "source": (
                Path(src_input_path).name
                if (src_input_path and req.include_source_filename) else None
            ),
            "seed": req.seed,
            "core": {
                "speed":                 req.speed,
                "resolution":            req.resolution,
                "transient_sensitivity": req.transient_sensitivity,
                "envelope_ms":           req.envelope_ms,
                "preserve_pitch":        req.preserve_pitch,
                "pitch_shift_semitones": req.pitch_shift_semitones,
                "randomize_order":       req.randomize_order,
                "reverse_chance":        req.reverse_chance,
                "stutter_chance":        req.stutter_chance,
                "stutter_skip_ms":       req.stutter_skip_ms,
                "stutter_max_reps":      req.stutter_max_reps,
                "stutter_spread":        req.stutter_spread,
                "beat_trim_start_ms":    req.beat_trim_start_ms,
                "beat_trim_end_ms":      req.beat_trim_end_ms,
                "beat_gap_ms":           req.beat_gap_ms,
                "bpm_override":          req.bpm_override,
                "beat_mask":             req.beat_mask,
                # Note-mode (mode, note) pairs (ADR-0020)
                "stutter_skip_mode":     req.stutter_skip_mode,
                "stutter_skip_note":     req.stutter_skip_note,
                "beat_trim_start_mode":  req.beat_trim_start_mode,
                "beat_trim_start_note":  req.beat_trim_start_note,
                "beat_trim_end_mode":    req.beat_trim_end_mode,
                "beat_trim_end_note":    req.beat_trim_end_note,
                "beat_gap_mode":         req.beat_gap_mode,
                "beat_gap_note":         req.beat_gap_note,
            },
            "fx": {
                "dist_drive":  req.dist_drive,
                "ring_freq":   req.ring_freq,
                "ring_depth":  req.ring_depth,
                "delay_time":  req.delay_time,
                "delay_fb":    req.delay_fb,
                "delay_mix":   req.delay_mix,
                "phase_rate":  req.phase_rate,
                "phase_depth": req.phase_depth,
            },
            "audio_source": req.audio_source_label,
            "rendered_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        patch_blob = json.dumps(patch, separators=(",", ":"))

        # Step 3 — build the output filename.
        _set(0.15, "Naming output…")
        safe_title = _safe_title(req.title_text or "")
        jumble = _jumble_name(
            src_input_path or "untitled",
            length=16,
            seed=req.seed,
        )
        parts = ["Subvoyant_Siena_Slurmify"]
        if safe_title:
            parts.append(safe_title)
        parts.append(jumble)
        fname = "_".join(parts) + ".mp4"
        out_path = slurmio._new_temp_path(suffix=f"_{fname}", prefix="slurmvid_")

        # Step 4 — MP4 metadata atoms.  YouTube reads title, artist,
        # date, and description; we embed PATCH= as a suffix on
        # description so it's both human-readable AND machine-parseable.
        title_for_meta   = (req.title_text   or "").strip() or f"Subvoyant Slurm {jumble}"
        creator_for_meta = (req.creator_text or "").strip() or "Subvoyant SIENA Slurmer"
        year = datetime.now(timezone.utc).strftime("%Y")

        description = (
            "Made with Subvoyant SIENA Slurmer · https://subvoyant.com\n"
            f"Speed: {patch['core']['speed']}× · "
            f"Resolution: {patch['core']['resolution']} · "
            f"Seed: {patch['seed']}\n"
            "\n"
            f"PATCH={patch_blob}"
        )

        metadata = {
            "title":        title_for_meta,
            "artist":       creator_for_meta,
            "album":        "Subvoyant Slurms",
            "album_artist": "Subvoyant",
            "genre":        "Slurm",
            "date":         year,
            "encoder":      f"Subvoyant SIENA Slurmer v{__version__}",
            "comment":      "made with Subvoyant SIENA Slurmer · subvoyant.com",
            "description":  description,
            "synopsis":     "A slurmified audio remix.",
        }

        # Step 5 — run ffmpeg.  Stream-copy the video; AAC-encode audio;
        # +faststart so YouTube can begin reading metadata before the
        # whole file is uploaded.
        _set(0.25, "Rendering MP4 (ffmpeg)…")

        ffmpeg_exe = (
            shutil.which("ffmpeg")
            or os.environ.get("FFMPEG_BINARY", "ffmpeg")
        )

        # -stream_loop -1 makes ffmpeg loop the input video forever; -t
        # (or -shortest) trims to the audio length.  We use -shortest
        # because we don't have an explicit duration here.
        cmd = [
            ffmpeg_exe, "-y",
            "-stream_loop", "-1",
            "-i", loop_path,
            "-i", audio_path,
            "-map", "0:v:0",        # video from the loop
            "-map", "1:a:0",        # audio from the slurm output
            "-c:v", "copy",         # ADR-0006: never re-encode the video
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",         # YouTube prefers 48 kHz audio in MP4
            "-shortest",
            "-movflags", "+faststart",
        ]
        for k, v in metadata.items():
            cmd.extend(["-metadata", f"{k}={v}"])
        cmd.append(out_path)

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            err_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
            print(f"[slurm-api] ffmpeg render failed: {err_tail}", file=sys.stderr)
            raise RuntimeError(f"ffmpeg failed: {err_tail[:300]}")

        # Step 6 — register and finish.
        _set(0.95, "Finalizing…")
        output_id = register_file(out_path)
        _set(1.0, "Done ✓")
        job.mark_done(output_id=output_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        job.mark_done(error=f"render-video failed: {type(e).__name__}: {e}")
