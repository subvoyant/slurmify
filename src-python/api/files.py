"""
src-python/api/files.py — File registry + range-aware file serving
─────────────────────────────────────────────────────────────────────

Every file the backend creates or accepts (uploads, slurm outputs, FX
burns, video renders) is registered with a UUID-prefixed `file_id` so
the React frontend can reference it by ID rather than by path.  The
actual files live inside slurmio's session-scoped temp directory, which
is automatically wiped on process exit (ADR-0011 carries forward).

Why a registry instead of just exposing the temp dir directly?
  1. Path security: never let the client request an arbitrary path.
     With a registry, only files we explicitly registered are servable.
  2. Stable IDs: the React frontend stores the file_id in Zustand
     state; using the basename keeps the URL stable even if the
     underlying filename changes (e.g., format conversion).
  3. Cleanup integration: tying file_id to slurmio paths means
     auto-cleanup on session exit Just Works.

────────────────────────────────────────────────────────────────────
HTTP range requests (the load-bearing reason this module is non-trivial)
────────────────────────────────────────────────────────────────────
WaveSurfer issues HTTP range requests when the user clicks somewhere in
a long waveform — without range support, the entire audio file is
re-fetched on every seek.  For a 5-minute stereo WAV (~50 MB) that's
brutal over even local HTTP.

This module handles `Range: bytes=START-END` headers and returns 206
Partial Content responses with the right `Content-Range`, `Accept-Ranges`,
and `Content-Length` headers.  WaveSurfer (via the underlying HTML
<audio> element) then handles seek-without-refetch correctly.

The 206 path streams 64 KB chunks rather than reading the whole range
into memory — irrelevant for short audio but matters for long video
exports where a "play from the middle" request shouldn't allocate
hundreds of MB.
"""

from __future__ import annotations

import os
from typing import Iterator
from fastapi import APIRouter, Header, HTTPException, Path
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter(tags=["files"])

# ── Internal registry ───────────────────────────────────────────────────
# Maps file_id (a stable string the client uses) → absolute path on disk.
# Populated by register_file() from upload, slurmify, fx, render endpoints.
# We use os.path.basename(path) as the file_id by default — it is unique
# inside SESSION_TMP_DIR (slurmio always uses tempfile.mkstemp under
# SESSION_TMP_DIR which guarantees uniqueness).
_FILES: dict[str, str] = {}


def register_file(path: str) -> str:
    """Register a path with the file server and return its public file_id.

    The caller is expected to have produced `path` via slurmio's
    _new_temp_path or equivalent — i.e., it should already live inside
    SESSION_TMP_DIR so it gets wiped at exit.

    Parameters
    ----------
    path : str
        Absolute filesystem path to a registered file.

    Returns
    -------
    str
        The file_id (currently the basename of the path).  Stable across
        the process lifetime; not stable across sidecar restarts.

    Raises
    ------
    FileNotFoundError
        If path doesn't exist on disk at registration time.  This catches
        "I forgot to actually write the file before registering" bugs.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"can't register non-existent file: {path}")
    file_id = os.path.basename(path)
    _FILES[file_id] = path
    return file_id


def resolve_file(file_id: str) -> str | None:
    """Look up a registered file_id and return its absolute path, or None.

    Used by other endpoints (slurmify reads the source file, render
    reads the slurm output, etc.) to translate a client-side file_id
    into an actual disk path.
    """
    return _FILES.get(file_id)


# ── Content-type guessing ───────────────────────────────────────────────
# Minimal table — only the types we actually produce.  We avoid the
# stdlib's mimetypes module because its default DB is platform-specific
# and we want consistent Content-Type headers across macOS/Linux.
_CONTENT_TYPES = {
    ".wav":  "audio/wav",
    ".flac": "audio/flac",
    ".mp3":  "audio/mpeg",
    ".m4a":  "audio/mp4",
    ".aac":  "audio/aac",
    ".aiff": "audio/aiff",
    ".ogg":  "audio/ogg",
    ".mp4":  "video/mp4",
    ".mov":  "video/quicktime",
    ".webm": "video/webm",
}


def _content_type_for(path: str) -> str:
    """Pick a Content-Type from the file extension.  Default to octet-stream."""
    ext = os.path.splitext(path)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


# ── Endpoint: GET /files/{id} ───────────────────────────────────────────

@router.get("/files/{file_id}")
def serve_file(
    file_id: str = Path(..., description="The file_id returned by /upload, /slurmify, etc."),
    range:   str | None = Header(default=None, description="HTTP Range header (RFC 7233)."),
):
    """Stream a registered file with optional byte-range support.

    The full-content path uses FastAPI's FileResponse (zero-copy when
    possible).  The range path streams 64 KB chunks for memory safety
    on large files.

    Frontend implication: the React `<audio src="…/files/{id}">` element
    relies on Accept-Ranges + 206 responses to seek without refetching.
    Don't drop the range support without thinking carefully about the
    WaveSurfer UX.
    """
    path = resolve_file(file_id)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"unknown file_id: {file_id}")

    file_size    = os.path.getsize(path)
    content_type = _content_type_for(path)

    # ── No Range header → full file, 200 OK ────────────────────────────
    if range is None or not range.startswith("bytes="):
        return FileResponse(
            path,
            media_type=content_type,
            headers={"Accept-Ranges": "bytes"},
        )

    # ── Parse "bytes=START-END" — both START and END are optional ──────
    #
    # Per RFC 7233:
    #   bytes=0-499      → first 500 bytes (start=0, end=499)
    #   bytes=500-       → from byte 500 to end of file
    #   bytes=-500       → last 500 bytes (suffix range)
    #
    # We handle the first two cases (the common ones for media seeking).
    # Suffix ranges are decoded too — WaveSurfer doesn't typically use
    # them, but supporting them is cheap.
    rng_str = range[len("bytes="):]
    start_s, _, end_s = rng_str.partition("-")
    try:
        if start_s == "" and end_s != "":
            # Suffix range: last N bytes.
            suffix_len = int(end_s)
            start = max(0, file_size - suffix_len)
            end   = file_size - 1
        else:
            start = int(start_s) if start_s else 0
            end   = int(end_s) if end_s else file_size - 1
    except ValueError:
        # Malformed Range header → 416 (Range Not Satisfiable).
        raise HTTPException(
            status_code=416,
            detail=f"bad Range header: {range}",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    # Clamp end to the actual file size; reject ranges entirely past EOF.
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail=f"range out of bounds: {range} for size {file_size}",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    length = end - start + 1

    def chunk_stream() -> Iterator[bytes]:
        """Yield 64 KB chunks of the requested byte range.

        We open the file once per request (cheap on macOS local FS).
        If the client closes the connection mid-stream, the generator
        gets garbage-collected and the file handle closes naturally.
        """
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 64 * 1024
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range":  f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges":  "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(
        chunk_stream(),
        status_code=206,
        media_type=content_type,
        headers=headers,
    )


# ── Endpoint: GET /files/{id}/download — same content, force-save header

@router.get("/files/{file_id}/download")
def download_file(file_id: str):
    """Same as /files/{id} but with a Content-Disposition: attachment header.

    Used by a "Save As…" UX path in the frontend so the browser shows a
    save dialog instead of trying to play the audio inline.
    """
    path = resolve_file(file_id)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"unknown file_id: {file_id}")

    return FileResponse(
        path,
        media_type=_content_type_for(path),
        filename=os.path.basename(path),
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
    )
