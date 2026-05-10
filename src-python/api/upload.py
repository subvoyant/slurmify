"""
src-python/api/upload.py — File ingestion endpoint
─────────────────────────────────────────────────────────────────────

Accepts ANY file (audio or video) via multipart upload.  Audio passes
straight through to the file registry.  Video files are routed through
ffmpeg -vn to extract a 16-bit 44 100 Hz stereo WAV before being
registered — same logic as `_route_upload` in v0.1.6's slurm_ui.py
(ADR-0009 carries forward).

Why the routing distinction lives server-side rather than in the React
frontend:
  • Slurmcore expects audio array input.  The video → audio conversion
    is a backend concern (ffmpeg lives in the sidecar bundle).
  • Keeps the frontend file-handling code simple: drop file, get
    file_id, render waveform.  No client-side ffmpeg-wasm needed.
  • Mirrors the v0.1.6 user-experience: "drop any media file, get
    audio out" Just Works.

Returns metadata the frontend uses to render the input panel: file_id
(stable URL key), original filename, duration in seconds, channel count,
sample rate, format extension.  Duration + channel count come from a
quick librosa probe — not a full load (we don't want to decode a long
file twice).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

# Slurmify shared modules (one level up from src-python/).
# server.py adds the project root to sys.path so these imports work.
import slurmio
import soundfile as sf

from api.files import register_file

router = APIRouter(tags=["upload"])

# ── Audio-vs-video routing extension whitelist ──────────────────────────
# Audio extensions pass straight through.  Anything not in this set is
# treated as a video / container file and routed through ffmpeg -vn.
# Mirrors _AUDIO_EXTS in v0.1.6 slurm_ui.py.
_AUDIO_EXTS = frozenset({
    ".mp3", ".wav", ".aif", ".aiff", ".aac", ".m4a",
    ".flac", ".ogg", ".opus", ".wma", ".ape", ".alac",
})


def _ffmpeg_extract_audio(src_path: str) -> str:
    """Run ffmpeg -vn on src_path and return the path to the extracted WAV.

    Output is a 16-bit PCM stereo WAV at 44 100 Hz (TARGET_SR) so
    slurmio.load_audio sees the format it expects.

    The output file is created via slurmio._new_temp_path so it lives
    inside SESSION_TMP_DIR and gets auto-cleaned at exit.

    Raises gr.Error-equivalent (HTTPException 400) if ffmpeg fails — the
    frontend surfaces this as a toast.
    """
    out_path = slurmio._new_temp_path(suffix=".wav", prefix="extracted_")

    # Find ffmpeg the same way v0.1.6 did: bundled-bin first, then PATH,
    # then FFMPEG_BINARY env var as a last resort.  PyInstaller's bootstrap
    # in app.py prepends the bundled bin/ to PATH, so shutil.which finds
    # the static binary in the .app bundle.
    ffmpeg_exe = (
        shutil.which("ffmpeg")
        or os.environ.get("FFMPEG_BINARY", "ffmpeg")
    )

    try:
        subprocess.run(
            [
                ffmpeg_exe, "-y",
                "-i", src_path,
                "-vn",                   # drop video stream
                "-acodec", "pcm_s16le",  # 16-bit PCM WAV
                "-ar", str(slurmio.TARGET_SR),  # match slurmio's TARGET_SR (44100)
                "-ac", "2",              # stereo (slurmio.load_audio preserves it after ADR-0021)
                out_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        # ffmpeg's stderr tail is usually the most diagnostic part.
        err_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
        print(f"[slurm-api] ffmpeg extraction failed: {err_tail}", file=sys.stderr)
        raise HTTPException(
            status_code=400,
            detail=f"Couldn't extract audio. ffmpeg said: {err_tail[:200]}",
        )

    return out_path


def _probe_audio_metadata(path: str) -> dict:
    """Return {duration_sec, channels, sample_rate, format} for a file.

    Uses soundfile's lightweight info() probe, which reads only the
    header — much faster than a full librosa load.  For formats
    soundfile can't probe directly (mp3 in older versions, video
    containers), we fall back to a librosa load with duration=0 to
    let it use audioread + ffmpeg, then report what comes back.
    """
    try:
        info = sf.info(path)
        return {
            "duration_sec": float(info.frames) / float(info.samplerate),
            "channels":     int(info.channels),
            "sample_rate":  int(info.samplerate),
            "format":       info.format,   # e.g. "WAV", "FLAC"
        }
    except Exception:
        # Soundfile can't probe → fall back to a tiny librosa load just
        # to get duration/channels (it routes through ffmpeg/audioread).
        # We deliberately don't load the full file here — that's the
        # caller's job inside slurmify.
        import librosa
        y, sr = librosa.load(path, sr=None, mono=False, duration=0.1)
        return {
            "duration_sec": float(librosa.get_duration(path=path)),
            "channels":     int(y.shape[0]) if y.ndim == 2 else 1,
            "sample_rate":  int(sr),
            "format":       Path(path).suffix.lstrip(".").upper(),
        }


# ── Endpoint: POST /upload ──────────────────────────────────────────────

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Accept an audio or video file; route + register; return metadata.

    Flow
    ────
      1. Stream the upload to disk inside SESSION_TMP_DIR (slurmio's
         temp area, auto-cleaned at exit).
      2. If the extension is in _AUDIO_EXTS, register that path.
      3. Otherwise, run ffmpeg -vn and register the extracted WAV.
      4. Probe the registered file for duration/channels/sample-rate.
      5. Return file_id + metadata.

    Returns
    ──────
    dict
        ```
        {
          "file_id": "slurmify_xxxx.wav",
          "name":    "original_filename.mp4",   # what the user dropped
          "duration_sec": 183.7,
          "channels":     2,
          "sample_rate":  44100,
          "format":       "WAV",
          "was_extracted": true                  # true if ffmpeg ran
        }
        ```

    Errors
    ──────
    400  if ffmpeg extraction fails on a video file.

    Diagnostics
    ───────────
    Every entry, success, and failure is printed to stdout with a
    `[slurm-api/upload]` prefix.  In a bundled DMG those lines surface
    in `Console.app` under the `slurmify-backend` process — the
    fastest way to triage when the React DropZone reports a failure
    without enough detail (the original v0.2.0 build did exactly that;
    see the "two stacked 'upload failed' lines" incident, May 2026).
    Keep these prints — they cost effectively nothing and they're the
    first thing future-us reaches for when an upload regresses.
    """
    print(
        f"[slurm-api/upload] received: name={file.filename!r} "
        f"content_type={file.content_type!r}",
        flush=True,
    )
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="upload missing filename")

        original_name = file.filename
        ext = Path(original_name).suffix.lower()

        # Step 1 — write the upload to a session-temp file.  We use the
        # original extension so slurmio routing (which checks ext) works.
        saved_path = slurmio._new_temp_path(suffix=ext or ".bin", prefix="upload_")
        bytes_written = 0
        with open(saved_path, "wb") as out:
            # FastAPI streams the upload; copy in chunks to avoid loading
            # multi-GB files into memory.
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bytes_written += len(chunk)
        print(
            f"[slurm-api/upload] streamed {bytes_written} bytes to {saved_path}",
            flush=True,
        )

        # Step 2 / 3 — route by extension.
        was_extracted = False
        if ext in _AUDIO_EXTS:
            registered_path = saved_path
        else:
            # Anything not in _AUDIO_EXTS is treated as video / container.
            # _ffmpeg_extract_audio raises HTTPException 400 on failure.
            print(
                f"[slurm-api/upload] ext {ext!r} not in audio whitelist — "
                "running ffmpeg -vn",
                flush=True,
            )
            registered_path = _ffmpeg_extract_audio(saved_path)
            was_extracted = True
            # Best-effort: delete the original upload so we don't double-store.
            # If the unlink fails (rare; permissions), the session cleanup
            # will sweep it up at exit.
            try:
                os.unlink(saved_path)
            except OSError:
                pass

        # Step 4 — probe metadata for the frontend.
        meta = _probe_audio_metadata(registered_path)

        # Step 5 — register and return.
        file_id = register_file(registered_path)
        print(
            f"[slurm-api/upload] OK file_id={file_id} "
            f"duration={meta.get('duration_sec'):.2f}s "
            f"channels={meta.get('channels')} "
            f"sr={meta.get('sample_rate')} extracted={was_extracted}",
            flush=True,
        )
        return {
            "file_id":       file_id,
            "name":          original_name,
            "was_extracted": was_extracted,
            **meta,
        }
    except HTTPException:
        # Already a clean 4xx — let FastAPI surface it.  Re-log for the
        # console trail, then re-raise so the response is unchanged.
        raise
    except Exception as e:
        # Anything else is a programming bug we want the operator to see.
        # FastAPI's default exception handler turns this into a 500 with
        # an empty body, which is exactly the failure mode that produced
        # the "two stacked 'upload failed' lines" UI mystery.  Print the
        # full traceback so the sidecar log has it, then re-raise as an
        # HTTPException with the message in the body so the React side
        # can display it.
        import traceback
        print(
            f"[slurm-api/upload] UNHANDLED {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"upload handler crashed: {type(e).__name__}: {e}",
        )
