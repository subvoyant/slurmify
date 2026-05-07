"""slurmio.py — Filesystem IO for the Slurmify audio application.

This module is Phase 3 of the Slurmify modularisation (ADR-0017).
It extracts all filesystem read/write operations out of app.py so that
the core audio DSP (slurmcore.py) and the UI wiring (app.py) can focus
on what they do without being cluttered by disk mechanics.

────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE DOES
────────────────────────────────────────────────────────────────────────
  • Resolves paths to bundled assets (works in both dev and .app bundle)
  • Manages the per-session temp directory: create on startup, sweep
    orphans from crashed prior runs, clean up on exit via atexit
  • Provides _new_temp_path() so every caller gets a session-scoped
    temp file rather than leaking into the system temp dir
  • Opens the temp directory in the host OS file browser (_reveal_temp_dir)
  • Loads any supported audio/video file into a mono float32 numpy array
    (load_audio)
  • Writes a numpy audio array to a temp file in any supported format
    (_write_audio) — WAV/FLAC/OGG/AIFF via soundfile, MP3/AAC via ffmpeg

────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE DOES NOT DO
────────────────────────────────────────────────────────────────────────
  • Signal processing — that lives in slurmcore.py (pure DSP, numpy only)
  • Gradio event wiring — that lives in app.py
  • Any Web Audio / JavaScript / CSS — that lives in ui_assets.py

────────────────────────────────────────────────────────────────────────
4-MODULE ARCHITECTURE (after Phase 3)
────────────────────────────────────────────────────────────────────────
  app.py        — bootstrap + Gradio launch + UI event handlers
  ui_assets.py  — static browser content (JS, CSS, base64 images)
  slurmcore.py  — pure audio DSP (ADR-0016)
  slurmio.py    — filesystem IO ← THIS FILE (ADR-0017)

────────────────────────────────────────────────────────────────────────
PURITY RULE
────────────────────────────────────────────────────────────────────────
This module must never import gradio at the module level.  The lazy
  import gradio as _gr
inside _reveal_temp_dir's except handler is the single allowed exception
— it is deferred to call time precisely so PyInstaller can analyse this
file without requiring gradio to be installed in the analysis environment.

Allowed imports at module level:
    atexit  glob  os  platform  shutil  subprocess  sys  tempfile
    librosa  numpy  soundfile

Never add top-level:  gradio  pyrubberband  scipy  slurmcore  ui_assets

────────────────────────────────────────────────────────────────────────
PYINSTALLER
────────────────────────────────────────────────────────────────────────
"slurmio" must be listed in hiddenimports in slurmify.spec.  Local .py
modules are invisible to PyInstaller's static import scanner; if the
entry is missing the bundled .app will crash on startup with
  ModuleNotFoundError: No module named 'slurmio'

See ADR-0017 for rationale and ADR-0011 for the original session-temp
design this module now owns.
"""

# ── Standard library ─────────────────────────────────────────────────────────
import atexit          # register _cleanup_session_tmp to run on normal exit
import glob            # pattern-match orphaned session dirs on startup
import os              # path manipulation, file existence, os.unlink, os.close
import platform        # detect Darwin/Windows/Linux for _reveal_temp_dir
import shutil          # rmtree (cleanup), which (locate ffmpeg)
import subprocess      # run ffmpeg for MP3/AAC encoding, Popen for file browser
import sys             # detect frozen bundle mode (sys.frozen, sys._MEIPASS)
import tempfile        # mkdtemp / mkstemp for session-scoped temp files

# ── Third-party ──────────────────────────────────────────────────────────────
# These are all pure IO operations on numpy arrays — no signal processing here.
import librosa         # load audio from any format (mp3, aac, video, …) via ffmpeg
import numpy as np     # array type used in load_audio / _write_audio signatures
import soundfile as sf # write WAV / FLAC / OGG / AIFF without an ffmpeg round-trip


# ============================================================================
# Asset path resolution
# ============================================================================
#
# Slurmify ships as a macOS .app bundle built by PyInstaller.  Inside the
# bundle, data files (GIF, MP4, ICO, …) live under sys._MEIPASS — a temp
# directory PyInstaller unpacks at launch.  In the dev environment they sit
# beside app.py.  _asset() abstracts that difference so every call site can
# just write  _asset("assets/siena_dancer.gif")  regardless of context.
# ============================================================================

def _asset(relative_path: str) -> str:
    """Return the absolute path to a bundled asset file.

    Works in both the dev environment (path relative to the project root)
    and inside the frozen .app bundle (path relative to sys._MEIPASS).

    Parameters
    ----------
    relative_path : str
        Path to the asset, relative to the project root / bundle root.
        Example: "assets/siena_dancer.gif"

    Returns
    -------
    str
        Absolute filesystem path to the asset.
    """
    # sys.frozen is True when running inside a PyInstaller-built .app bundle.
    # In that case, PyInstaller has already unpacked all bundled data into the
    # temporary sys._MEIPASS directory.
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        # Dev mode: assets live relative to this source file.
        # __file__ here resolves to slurmio.py, which sits beside app.py;
        # both are at the project root, so the relative_path works the same.
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# ============================================================================
# Session-scoped temporary directory
# ============================================================================
#
# All audio outputs and video exports go into a per-session subdirectory of
# the system temp dir (e.g. /tmp/slurmify-session-abc123/).  This has two
# advantages over scattering files in /tmp directly:
#
#   1. Cleanup is one rmtree call rather than tracking individual files.
#   2. Multiple simultaneous Slurmify instances each get their own subdir
#      and never trample each other's cleanup.
#
# On normal Python exit, atexit fires _cleanup_session_tmp.
# On startup we also sweep up any slurmify-session-* dirs left by prior
# crashes that hit SIGKILL before atexit could run.
#
# IMPORTANT: This module-level code runs once when slurmio is imported.
# That happens during app.py startup, after the PyInstaller bootstrap has
# already set up PATH and environment variables — so tempfile.mkdtemp()
# will write to the correct system temp dir.
# ============================================================================

# Create the session temp dir immediately at import time.  The mkdtemp call
# is side-effect-free for callers: it creates one empty directory in the
# system temp area and records its path.
SESSION_TMP_DIR: str = tempfile.mkdtemp(prefix="slurmify-session-")


def _cleanup_session_tmp() -> None:
    """Remove this session's temp directory and everything inside it.

    Called by atexit on normal Python exit (Ctrl-C, normal quit).
    Uses ignore_errors=True so a missing-or-already-deleted dir is harmless
    — the goal is best-effort cleanup, not a crash on the way out.
    """
    shutil.rmtree(SESSION_TMP_DIR, ignore_errors=True)


# Register the cleanup function.  atexit guarantees it runs when Python exits
# normally (including Gradio's signal handling).  It will NOT run on SIGKILL
# (force-quit) — that's what _sweep_orphan_session_dirs handles on next boot.
atexit.register(_cleanup_session_tmp)


def _sweep_orphan_session_dirs() -> None:
    """Delete leftover slurmify-session-* directories from prior crashed runs.

    When Slurmify is force-killed (Activity Monitor → Force Quit, or
    macOS crash recovery), the atexit handler never fires and SESSION_TMP_DIR
    from that run stays on disk indefinitely.  This function runs once at
    startup to recover that space.

    Safety measures:
      - Skips the CURRENT session dir (we just created it above).
      - Only removes directories whose names start with our known prefix.
      - Fails silently: leftover dirs are annoying but never worth a crash.
    """
    # Build a glob pattern like /tmp/slurmify-session-* and iterate matches.
    pattern = os.path.join(tempfile.gettempdir(), "slurmify-session-*")
    for old_dir in glob.glob(pattern):
        # Never delete the dir we just created for this session.
        if old_dir == SESSION_TMP_DIR:
            continue
        try:
            # Extra sanity check: only touch actual directories.
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)
        except Exception:
            # Swallow everything — permissions, race conditions, network mounts.
            # This is opportunistic cleanup, not a critical path.
            pass


# Run the orphan sweep immediately.  This runs once at module import time,
# which is early in app.py startup — before any Gradio UI is built.
_sweep_orphan_session_dirs()


def _new_temp_path(suffix: str, prefix: str = "slurmify_") -> str:
    """Create a unique temp file inside SESSION_TMP_DIR and return its path.

    Why not use tempfile.mkstemp() directly?
    → Direct mkstemp() calls scatter files into the system /tmp root and
      bypass our session-cleanup machinery.  Every temp file produced by
      Slurmify MUST go through this function so it lives inside SESSION_TMP_DIR
      and gets automatically wiped on exit.

    The returned path is immediately usable — the underlying file descriptor
    is closed right away.  Callers write to it themselves (sf.write, ffmpeg
    subprocess, etc.) using whatever mode they need.

    Parameters
    ----------
    suffix : str
        File extension including the dot.  Example: ".wav", ".mp3", ".mp4"
    prefix : str
        Optional filename prefix.  Defaults to "slurmify_".

    Returns
    -------
    str
        Absolute path to an empty file inside SESSION_TMP_DIR.
    """
    # mkstemp creates the file and returns (file_descriptor, path).
    # We close the fd immediately because callers open the path themselves.
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=SESSION_TMP_DIR)
    os.close(fd)
    return path


def _reveal_temp_dir() -> None:
    """Open SESSION_TMP_DIR in the host OS file browser.

    This is wired to the 📁 "reveal temp files" button in app.py.
    Platform detection:
        macOS   → open (Finder)
        Windows → explorer
        Linux   → xdg-open (works with GNOME Files, Nautilus, Dolphin, …)

    On failure (e.g. Finder not available in a headless environment) the
    exception is re-raised as gr.Error so Gradio surfaces it as a friendly
    red banner rather than a raw Python traceback.

    Note on the deferred gradio import:
        We import gradio inside the except handler, not at module level.
        This keeps slurmio.py importable in contexts where gradio is not
        installed — specifically PyInstaller's static analysis pass, which
        scans imports to build its dependency graph.  If gradio were at
        the top level here, the analysis might try to bundle it twice or
        flag a conflict.  The lazy import only fires on actual failures,
        which only happen at Gradio runtime (where gradio is always present).
    """
    system = platform.system()
    print(f"[slurm] revealing temp dir: {SESSION_TMP_DIR}")
    try:
        if system == "Darwin":
            # macOS: `open` tells Finder to reveal the directory.
            subprocess.Popen(["open", SESSION_TMP_DIR])
        elif system == "Windows":
            # Windows: `explorer` opens the folder in File Explorer.
            subprocess.Popen(["explorer", SESSION_TMP_DIR])
        else:
            # Linux / BSD: xdg-open delegates to whatever file manager is
            # registered in the desktop environment.
            subprocess.Popen(["xdg-open", SESSION_TMP_DIR])
    except Exception as e:
        # Don't crash the app on a desktop-integration hiccup.
        # Deferred import — see docstring for why this is not at module level.
        import gradio as _gr  # noqa: PLC0415
        raise _gr.Error(f"Couldn't open temp folder: {e}")


# ============================================================================
# Audio input
# ============================================================================
#
# load_audio is the single entry point for reading any supported audio or
# video file.  librosa handles format detection and delegates to audioread /
# ffmpeg for compressed formats (MP3, AAC, M4A) and video containers.
#
# The output is always:
#   - mono  (stereo/surround tracks are mixed down to a single channel)
#   - float32  (values in [-1.0, 1.0])
#   - 44 100 Hz  (resampled from whatever the source uses)
#
# This normalised representation is what slurmcore.py expects.  burn_fx()
# in app.py deliberately bypasses load_audio and calls librosa.load directly
# (with sr=None, mono=False) to preserve the original SR and channel layout
# for the FX chain — that's intentional.
# ============================================================================

# Set of file extensions that the upload handler in app.py accepts.
# Audio formats: librosa + ffmpeg handle decoding.
# Video formats: audioread / ffmpeg demux the audio track transparently;
#   extension validation lets them through the check in process().
SUPPORTED_EXTS: frozenset[str] = frozenset({
    # Lossless / uncompressed audio
    ".wav", ".aif", ".aiff", ".flac", ".alac",
    # Compressed audio
    ".mp3", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".ape",
    # Video containers — librosa pulls audio via audioread + ffmpeg.
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv",
    ".mpg", ".mpeg", ".3gp", ".3g2", ".ts", ".mts", ".m2ts",
})

# Target sample rate for all processed audio.  44 100 Hz is standard CD
# quality and is understood by every consumer audio format and DAW.
# All load_audio output is resampled to this rate regardless of source SR.
TARGET_SR: int = 44_100


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load any supported audio or video file into a mono float32 array.

    This is the standard entry point for the slurmify processing pipeline.
    It always returns a mono, float32, 44 100 Hz numpy array so that
    slurmcore.py can make safe assumptions about the input shape.

    If the source is stereo or surround, librosa mixes the channels down to
    mono automatically (default behavior of librosa.load).

    Parameters
    ----------
    path : str
        Absolute path to any file in SUPPORTED_EXTS.  Video files are
        demuxed transparently: only the first audio stream is extracted.

    Returns
    -------
    y : np.ndarray, shape (n_samples,), dtype float32
        Audio time series.  Values are in the range [-1.0, 1.0].
    sr : int
        Sample rate.  Always TARGET_SR (44 100).
    """
    # librosa.load returns float64 by default; we cast to float32 to halve
    # memory usage and match what slurmcore's numpy operations expect.
    y, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    return y.astype(np.float32), sr


# ============================================================================
# Audio output
# ============================================================================
#
# _write_audio routes the caller's choice of format to the appropriate
# encoder backend:
#   WAV / FLAC / OGG / AIFF → soundfile (no subprocess, fast, lossless-capable)
#   MP3 / AAC               → ffmpeg (subprocess call; needs ffmpeg on PATH)
#
# All output files go into SESSION_TMP_DIR via _new_temp_path() so they are
# automatically cleaned up when the app exits.
# ============================================================================

# Formats that soundfile can write directly, without invoking ffmpeg.
# Each entry maps the user-visible format string to the soundfile parameters.
#   "suffix"  — file extension (including dot) for _new_temp_path()
#   "subtype" — soundfile subtype string (controls bit depth / codec)
_SF_FORMATS: dict[str, dict] = {
    "wav":  {"suffix": ".wav",  "subtype": "PCM_16"},   # 16-bit PCM WAV
    "flac": {"suffix": ".flac", "subtype": "PCM_16"},   # 16-bit lossless FLAC
    "ogg":  {"suffix": ".ogg",  "subtype": "VORBIS"},   # Ogg Vorbis (lossy)
    "aiff": {"suffix": ".aiff", "subtype": "PCM_16"},   # 16-bit AIFF (Apple)
}

# Formats that require ffmpeg encoding.  Workflow: write a lossless WAV
# intermediary, then transcode to the target format and delete the WAV.
#   "suffix"  — file extension for the final output file
#   "codec"   — ffmpeg -c:a codec name
#   "quality" — list of extra ffmpeg quality flags (inserted before out_path)
_FFMPEG_FORMATS: dict[str, dict] = {
    "mp3": {"suffix": ".mp3", "codec": "libmp3lame", "quality": ["-q:a", "2"]},
    # -q:a 2 → ~190 kbps VBR, visually transparent for most listeners
    "aac": {"suffix": ".m4a", "codec": "aac",        "quality": ["-b:a", "192k"]},
    # 192 kbps CBR AAC in an M4A container — standard for Apple ecosystem
}


def _write_audio(y: np.ndarray, sr: int, fmt: str) -> str:
    """Write an audio numpy array to a session-scoped temp file.

    Chooses the right encoder backend based on the requested format:
      - soundfile (fast, in-process) for WAV / FLAC / OGG / AIFF
      - ffmpeg subprocess for MP3 / AAC  (write temp WAV first, transcode)

    Falls back to WAV if the format string is not recognised.

    Parameters
    ----------
    y : np.ndarray
        Audio samples.  Shape: (n_samples,) for mono,
        or (n_samples, n_channels) for stereo (soundfile convention).
        Note: slurmcore's _fx_* helpers use (n_channels, n_samples);
        the caller (burn_fx in app.py) is responsible for transposing.
    sr : int
        Sample rate in Hz.  Typically TARGET_SR (44 100).
    fmt : str
        Desired output format.  One of: "wav", "flac", "ogg", "aiff",
        "mp3", "aac".  Case-insensitive.

    Returns
    -------
    str
        Absolute path to the newly written temp file inside SESSION_TMP_DIR.
    """
    fmt = fmt.lower()

    # ── soundfile path (no subprocess needed) ────────────────────────────────
    if fmt in _SF_FORMATS:
        cfg = _SF_FORMATS[fmt]
        path = _new_temp_path(suffix=cfg["suffix"])
        # sf.write expects y to be (n_samples,) for mono or
        # (n_samples, n_channels) for multi-channel — soundfile's convention.
        sf.write(path, y, sr, subtype=cfg["subtype"])
        return path

    # ── ffmpeg path (two-step: WAV intermediate → transcode) ─────────────────
    if fmt in _FFMPEG_FORMATS:
        cfg = _FFMPEG_FORMATS[fmt]

        # Step 1: write a lossless WAV so ffmpeg has something to read from.
        # Using a session-scoped temp path prevents leaking into /tmp root.
        wav_path = _new_temp_path(suffix=".wav", prefix="slurmify_tmp_")
        sf.write(wav_path, y, sr, subtype="PCM_16")

        # Step 2: find ffmpeg.  The PyInstaller bootstrap in app.py prepends
        # the bundled bin/ directory to PATH, so shutil.which finds the
        # static binary shipped in the .app bundle.  In dev mode it finds
        # whatever is on the system PATH (brew install ffmpeg).
        ffmpeg_exe = shutil.which("ffmpeg") or os.environ.get("FFMPEG_BINARY", "ffmpeg")

        # Build the output path before running ffmpeg.
        out_path = _new_temp_path(suffix=cfg["suffix"])

        try:
            # Run ffmpeg.  -y → overwrite without prompting (the file was just
            # created empty by _new_temp_path, so -y is a no-op in practice).
            # capture_output=True keeps ffmpeg's stderr out of the terminal.
            subprocess.run(
                [ffmpeg_exe, "-y", "-i", wav_path,
                 "-c:a", cfg["codec"], *cfg["quality"],
                 out_path],
                check=True,          # raise CalledProcessError on non-zero exit
                capture_output=True, # suppress ffmpeg's verbose stderr
            )
        finally:
            # Always delete the intermediate WAV, even if ffmpeg failed.
            # os.unlink is best-effort: if it fails (race, permission) we
            # silently accept the leak rather than masking the real error.
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        return out_path

    # ── Unknown format → fall back to WAV ────────────────────────────────────
    # This branch should never be reached in normal operation because the UI
    # only offers the formats listed above.  The fallback prevents a crash
    # if a future code path passes an unrecognised format string.
    return _write_audio(y, sr, "wav")
