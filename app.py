"""
Slurmify — a chopped, sped-up, transient-sliced audio remixer.

Single-file Python app. Drop in any audio file (mp3/aac/wav/aif/m4a/flac/ogg),
twist the knobs, get a slurm-style remix back.

Run:  python app.py
Then open the URL it prints (usually http://127.0.0.1:7860).
"""

from __future__ import annotations

import os
import sys
import random
import base64
import tempfile
import atexit
import shutil
import glob
from pathlib import Path

# ---------------------------------------------------------------------------
# PyInstaller bundle bootstrap
# Must run before any library import that touches native binaries.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # _MEIPASS is the temp dir where PyInstaller unpacks everything.
    _bundle_dir = sys._MEIPASS  # type: ignore[attr-defined]

    # 1. Put our vendored binaries (rubberband) first on PATH.
    _bin_dir = os.path.join(_bundle_dir, "bin")
    os.environ["PATH"] = _bin_dir + os.pathsep + os.environ.get("PATH", "")

    # 2. Disable numba JIT — it cannot compile inside a frozen bundle.
    os.environ.setdefault("NUMBA_DISABLE_JIT", "1")

# ---------------------------------------------------------------------------
# Wire up imageio-ffmpeg's bundled static binary so librosa/audioread
# can decode mp3/aac/m4a without a system ffmpeg install.
# Runs in both dev and bundled modes.
# ---------------------------------------------------------------------------
try:
    import imageio_ffmpeg as _iio_ffmpeg
    _ffmpeg_exe = _iio_ffmpeg.get_ffmpeg_exe()
    os.environ["PATH"] = os.path.dirname(_ffmpeg_exe) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("FFMPEG_BINARY", _ffmpeg_exe)
except Exception:
    pass  # fall back to whatever ffmpeg is on the system PATH

# ---------------------------------------------------------------------------
# Asset path helper — works in both dev and frozen bundle modes.
# In dev: looks relative to this file. In bundle: looks in sys._MEIPASS.
# ---------------------------------------------------------------------------
def _asset(relative_path: str) -> str:
    """Return the absolute path to a bundled asset file."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# ---------------------------------------------------------------------------
# Session-scoped temp directory — keeps user disks tidy.
#
# All audio outputs and video exports go into a per-session subdirectory of
# the system temp dir. On normal Python exit, atexit wipes the whole subdir.
# On startup we also sweep up any orphaned `slurmify-session-*` dirs from
# prior runs that crashed before atexit could fire (e.g. SIGKILL).
#
# Each running Slurmify instance gets its own SESSION_TMP_DIR, so multiple
# instances don't trample each other's cleanup.
# ---------------------------------------------------------------------------
SESSION_TMP_DIR = tempfile.mkdtemp(prefix="slurmify-session-")

def _cleanup_session_tmp() -> None:
    """Remove this session's temp dir on exit."""
    shutil.rmtree(SESSION_TMP_DIR, ignore_errors=True)

atexit.register(_cleanup_session_tmp)

def _sweep_orphan_session_dirs() -> None:
    """Delete leftover slurmify-session-* dirs from prior crashed runs."""
    pattern = os.path.join(tempfile.gettempdir(), "slurmify-session-*")
    for old_dir in glob.glob(pattern):
        if old_dir == SESSION_TMP_DIR:
            continue
        # Be defensive: only remove if it actually looks like our session dir
        # (a directory, name matches our prefix). Fail silently — orphans on
        # the next boot are not worth crashing the app over.
        try:
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)
        except Exception:
            pass

_sweep_orphan_session_dirs()

def _new_temp_path(suffix: str, prefix: str = "slurmify_") -> str:
    """Create a unique temp file inside SESSION_TMP_DIR and return its path.

    The fd is closed immediately — callers that want to write should open
    the path themselves with their preferred mode (sf.write, ffmpeg, etc.).
    Files placed here are auto-cleaned when the app exits.
    """
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=SESSION_TMP_DIR)
    os.close(fd)
    return path


def _reveal_temp_dir() -> None:
    """Open SESSION_TMP_DIR in the host OS file browser.

    macOS  → Finder via `open`
    Windows → Explorer via `explorer`
    Linux  → whatever is wired up via `xdg-open`
    """
    import subprocess
    import platform
    system = platform.system()
    print(f"[slurm] revealing temp dir: {SESSION_TMP_DIR}")
    try:
        if system == "Darwin":
            subprocess.Popen(["open", SESSION_TMP_DIR])
        elif system == "Windows":
            subprocess.Popen(["explorer", SESSION_TMP_DIR])
        else:
            subprocess.Popen(["xdg-open", SESSION_TMP_DIR])
    except Exception as e:
        # Don't crash the app on a desktop-integration hiccup; surface to UI.
        # Defer the gr import to call time so this module can be exec'd in
        # contexts that don't have gradio (e.g. PyInstaller analysis).
        import gradio as _gr  # noqa: PLC0415
        raise _gr.Error(f"Couldn't open temp folder: {e}")


import gradio as gr
import librosa
import numpy as np
import pyrubberband as pyrb
import soundfile as sf

# ---------------------------------------------------------------------------
# Audio engine
# ---------------------------------------------------------------------------

SUPPORTED_EXTS = {
    # Audio formats
    ".mp3", ".wav", ".aif", ".aiff", ".aac", ".m4a", ".flac", ".ogg",
    ".opus", ".wma", ".ape", ".alac",
    # Video / media containers — librosa pulls audio out via audioread + ffmpeg.
    # Listed here so the extension validation in process() lets them through;
    # actual demuxing happens transparently in load_audio().
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv",
    ".mpg", ".mpeg", ".3gp", ".3g2", ".ts", ".mts", ".m2ts",
}
TARGET_SR = 44_100  # standard CD-quality output


def load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load any common audio format into a mono float32 numpy array at 44.1kHz.

    librosa handles format conversion via audioread/ffmpeg under the hood,
    so we get mp3/aac/m4a support for free as long as ffmpeg is on PATH.
    """
    y, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    return y.astype(np.float32), sr


def detect_slice_points(
    y: np.ndarray,
    sr: int,
    resolution: str,
    transient_sensitivity: float,
    bpm_override: float | None = None,
) -> np.ndarray:
    """Return sample indices where the audio should be sliced.

    Two strategies are blended:
      1. Adaptive beat-grid slicing: detect BPM and beat positions, then
         subdivide or coarsen the actual beat positions rather than using a
         rigid uniform grid. This follows the track's natural tempo drift
         instead of drifting away from it. When the user supplies
         `bpm_override`, that value is passed to librosa as `start_bpm` so
         the tracker anchors to the correct octave (fixes 90 vs 180 BPM).
      2. Transient slicing: detect onsets and snap nearby grid points to them.

    `transient_sensitivity` (0.0–1.0) controls how much the onset detector
    influences slice placement. 0 = pure grid, 1 = pure onset detection.

    `bpm_override` (float or None): user-supplied BPM hint. When provided,
    it is passed to `librosa.beat.beat_track` as `start_bpm` to guide the
    tempo estimator toward the correct octave. The detected beat positions
    are still used for the adaptive grid — only the starting guess changes.
    """
    MIN_SAMPLES = 256  # ~6 ms at 44.1 kHz — minimum slice gap

    # MAX RANDOM mode: trimodal distribution — three categorical durations
    # with NO middle ground. Each slice is randomly drawn as one of:
    #   • stutter (5-30 ms)   — audio-rate buzzy blip, clusters as glitch bursts
    #   • chop    (100-500ms) — recognizable rhythmic chunk
    #   • held    (1000-4000ms) — long passage where audio almost plays through
    # We deliberately skip the 30-100 ms and 500-1000 ms ranges. Log-uniform
    # over a continuous span sounded "uniform" because the middle-ground
    # durations (100-500ms = chop tempo) dominated and the ear blended them
    # into a constant chop texture. Trimodal forces consecutive slices into
    # categorically different durations — your brain can't average them into
    # a single tempo.
    # Each category is internally log-uniform so within-category variation
    # is preserved. Seeded by the slurmify seed for reproducibility.
    # Sample floor 220 (~5 ms at 44.1 kHz) is the lower limit before the
    # slice envelope crossfade has no room to operate.
    # Named after Max the tester — and also "max" as in maximum entropy.
    if resolution == "MAX RANDOM":
        BUCKETS = [
            ("stutter", 5.0,    30.0),
            ("chop",    100.0,  500.0),
            ("held",    1000.0, 4000.0),
        ]
        positions = [0]
        pos = 0
        cat_counts = {"stutter": 0, "chop": 0, "held": 0}
        while pos < len(y):
            name, lo_ms, hi_ms = random.choice(BUCKETS)
            dur_ms = 10.0 ** random.uniform(np.log10(lo_ms), np.log10(hi_ms))
            dur_samples = max(220, int(sr * dur_ms / 1000.0))
            pos += dur_samples
            if pos < len(y):
                positions.append(pos)
                cat_counts[name] += 1
        # Debug: confirm at runtime that we hit this branch and the per-bucket
        # distribution. Should be roughly 1/3 stutter, 1/3 chop, 1/3 held.
        gaps = np.diff(positions) if len(positions) > 1 else np.array([0])
        gaps_ms = gaps * 1000.0 / sr
        n = len(positions)
        print(f"[slurm] MAX RANDOM trimodal emitted {n} positions · "
              f"stutter={cat_counts['stutter']} chop={cat_counts['chop']} "
              f"held={cat_counts['held']} · "
              f"durations min={gaps_ms.min():.0f}ms max={gaps_ms.max():.0f}ms "
              f"median={np.median(gaps_ms):.0f}ms")
        return np.array(positions, dtype=np.int64)

    # ── Tempo and beat detection ──────────────────────────────────────────
    # Keep beat_frames (not _) so the adaptive grid bends with tempo changes.
    # trim=False tells librosa not to discard leading/trailing beats, which
    # matters when the track starts with a pickup or fades out gradually.
    # bpm_override is passed as start_bpm — a hint, not a lock — so librosa
    # still refines the estimate from the audio; it just won't jump to a
    # harmonically-related wrong octave (e.g. 70 instead of 140).
    try:
        _kw = {"start_bpm": float(bpm_override)} if bpm_override else {}
        tempo, beat_frames = librosa.beat.beat_track(
            y=y, sr=sr, trim=False, **_kw
        )
        bpm = float(np.atleast_1d(tempo)[0])
        if bpm <= 0:
            bpm = float(bpm_override) if bpm_override else 120.0
        beat_samples = librosa.frames_to_samples(beat_frames).astype(np.int64)
    except Exception:
        beat_samples = np.array([], dtype=np.int64)
        bpm = float(bpm_override) if bpm_override else 120.0

    print(f"[slurm] BPM={bpm:.1f} beats={len(beat_samples)}"
          + (f" (override hint: {bpm_override})" if bpm_override else ""))

    # Convert resolution string to subdivisions per beat. Fractional values
    # (1/1, 1/2) mean fewer slices per beat — i.e. each slice spans multiple beats.
    res_map = {
        "1/1":   0.25, "1/2":  0.5,
        "1/4":   1,    "1/8":  2,
        "1/16":  4,    "1/32": 8,
        "1/64":  16,   "1/128": 32,
    }
    subdivs = res_map.get(resolution, 4)

    # ── Build adaptive grid from actual beat positions ────────────────────
    # When beat_samples is available, we subdivide or coarsen each inter-beat
    # interval individually so the grid follows the track's own tempo curve.
    # This is qualitatively better than a rigid np.arange grid for music
    # with gradual tempo drift, rubato, or a slightly unstable click track.
    #
    # Fallback: if librosa returned no beat positions, we fall back to a
    # uniform grid derived from the detected/overridden BPM.
    if len(beat_samples) >= 2:
        # Build a list of grid points by walking inter-beat intervals.
        # For subdivs >= 1: insert (subdivs-1) evenly-spaced points inside
        #   each beat span.
        # For subdivs < 1 (1/2 beat, 1/4 beat = whole / half note): collect
        #   every N-th beat as a grid point.
        grid_pts: list[int] = []

        if subdivs >= 1:
            n_sub = int(round(subdivs))
            for i in range(len(beat_samples) - 1):
                a, b = int(beat_samples[i]), int(beat_samples[i + 1])
                for k in range(n_sub):
                    pt = a + int(k * (b - a) / n_sub)
                    grid_pts.append(pt)
            # Include the last beat itself.
            grid_pts.append(int(beat_samples[-1]))
        else:
            # subdivs < 1 → every N-th beat is a slice boundary.
            step = max(1, int(round(1.0 / subdivs)))
            grid_pts = [int(beat_samples[i])
                        for i in range(0, len(beat_samples), step)]

        # Prepend sample 0 if not already there.
        if not grid_pts or grid_pts[0] > 0:
            grid_pts.insert(0, 0)

        # Extrapolate past the last detected beat to cover the tail of the
        # audio. Use the median inter-point spacing of the grid we just built
        # as the step size so the tail slice size is consistent with the body.
        if len(grid_pts) >= 2:
            spacing = int(np.median(np.diff(grid_pts)))
            spacing = max(spacing, MIN_SAMPLES)
            pos = grid_pts[-1] + spacing
            while pos < len(y):
                grid_pts.append(pos)
                pos += spacing

        # Enforce MIN_SAMPLES between consecutive points.
        filtered: list[int] = []
        for pt in sorted(set(grid_pts)):
            if not filtered or pt - filtered[-1] >= MIN_SAMPLES:
                filtered.append(pt)
        grid_points = np.array(filtered, dtype=np.int64)

        # Use median spacing (computed before filtering) for the transient
        # snap window — consistent with the adaptive grid density.
        median_spacing = int(np.median(np.diff(grid_points))) if len(grid_points) >= 2 else MIN_SAMPLES
    else:
        # No beat positions detected — fall back to uniform grid.
        samples_per_slice = max(MIN_SAMPLES, int(sr * 60.0 / bpm / subdivs))
        grid_points = np.arange(0, len(y), samples_per_slice, dtype=np.int64)
        median_spacing = samples_per_slice

    if transient_sensitivity <= 0.01:
        return grid_points

    # Onset detection. Higher sensitivity = lower threshold = more onsets.
    delta = max(0.01, 0.3 * (1.0 - transient_sensitivity))
    try:
        onset_frames = librosa.onset.onset_detect(
            y=y, sr=sr, delta=delta, backtrack=True
        )
        onset_samples = librosa.frames_to_samples(onset_frames)
    except Exception:
        onset_samples = np.array([], dtype=np.int64)

    if len(onset_samples) == 0:
        return grid_points

    if transient_sensitivity >= 0.99:
        return onset_samples

    # Hybrid: snap each grid point to the nearest onset within a window.
    # The window uses median_spacing (adaptive grid density) so it scales
    # correctly whether the resolution is 1/8 or 1/64.
    window = int(median_spacing * (1.0 - transient_sensitivity))
    snapped = []
    for gp in grid_points:
        candidates = onset_samples[np.abs(onset_samples - gp) <= window]
        snapped.append(int(candidates[np.argmin(np.abs(candidates - gp))]) if len(candidates) else int(gp))
    return np.array(sorted(set(snapped)), dtype=np.int64)


def apply_envelope(slice_audio: np.ndarray, sr: int, envelope_ms: float) -> np.ndarray:
    """Apply a short fade-in/out to a slice to avoid clicks at boundaries.

    envelope_ms = 0 → hard cuts (gritty, classic slurm clicks)
    envelope_ms > 0 → crossfades (smoother, more musical)
    """
    if envelope_ms <= 0 or len(slice_audio) < 4:
        return slice_audio
    n_fade = min(int(sr * envelope_ms / 1000.0), len(slice_audio) // 2)
    if n_fade < 2:
        return slice_audio
    fade_in = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, n_fade, dtype=np.float32)
    out = slice_audio.copy()
    out[:n_fade] *= fade_in
    out[-n_fade:] *= fade_out
    return out


def slurmify(
    input_path: str,
    speed: float,
    resolution: str,
    transient_sensitivity: float,
    envelope_ms: float,
    preserve_pitch: bool,
    pitch_shift_semitones: float,
    randomize_order: bool,
    reverse_chance: float,
    stutter_chance: float,
    stutter_skip_ms: float = 0.0,
    stutter_max_reps: int = 4,
    stutter_spread: float = 0.0,
    bpm_override: float | None = None,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    output_format: str = "wav",
    seed: int | None = None,
    _progress=None,
) -> str:
    """Run the full slurm transformation and write to a temp file.

    Returns the path to the rendered output file.
    _progress: optional callable(fraction, desc=str) for UI progress reporting.

    Stutter engine parameters:
      stutter_chance   — probability (0-1) each slice is stuttered
      stutter_skip_ms  — 0 = full-slice tile (classic); >0 = loop only the
                         first N ms of each slice (skip/stutter-edit mode)
      stutter_max_reps — upper bound for the random repeat count (2..max_reps)
      stutter_spread   — 0 = fixed skip length; 1 = skip length randomised
                         per-event from [skip_ms*(1-spread), skip_ms]

    BPM parameter:
      bpm_override     — optional float; when set, passed to librosa as
                         start_bpm to anchor beat tracking to the correct
                         tempo octave (e.g. 140 instead of 70).
    """
    def _prog(val: float, desc: str = "") -> None:
        if _progress is not None:
            _progress(val, desc=desc)

    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    _prog(0.05, "Loading audio…")
    y, sr = load_audio(input_path)

    # 0. Apply in/out trim (in seconds). end_sec=0 means use full file.
    start_sample = int(max(0.0, start_sec) * sr)
    end_sample   = int(end_sec * sr) if end_sec > 0.0 and end_sec > start_sec else len(y)
    end_sample   = min(end_sample, len(y))
    if start_sample > 0 or end_sample < len(y):
        y = y[start_sample:end_sample]
    if len(y) == 0:
        raise ValueError("In/out range is empty — check your start and end times.")

    _prog(0.15, "Time-stretching…")
    # 1. Time-stretch (or speed up with pitch shift if preserve_pitch is False).
    if preserve_pitch:
        # pyrubberband preserves pitch while changing tempo. Higher quality.
        y = pyrb.time_stretch(y, sr, speed)
    else:
        # Cheap resample = chipmunk effect (pitch goes up with speed).
        new_len = max(1, int(len(y) / speed))
        y = np.interp(
            np.linspace(0, len(y) - 1, new_len),
            np.arange(len(y)),
            y,
        ).astype(np.float32)

    # 1b. Independent pitch shift (semitones, ±24 = ±2 octaves).
    #     Applied after speed change so the two controls are fully independent.
    #     Skipped when zero to avoid an unnecessary rubberband pass.
    if pitch_shift_semitones != 0.0:
        _prog(0.28, "Shifting pitch…")
        y = pyrb.pitch_shift(y, sr, pitch_shift_semitones)

    _prog(0.40, "Finding slice points…")
    # 2. Find slice points on the (now sped-up) audio.
    slice_points = detect_slice_points(y, sr, resolution, transient_sensitivity,
                                       bpm_override=bpm_override)
    if len(slice_points) < 2:
        # Audio too short or detection failed — return as-is.
        _prog(0.95, "Encoding…")
        out_path = _write_audio(y, sr, output_format)
        _prog(1.0, "Done")
        return out_path

    _prog(0.50, "Slicing…")
    # 3. Cut into slices.
    slices = []
    for i in range(len(slice_points) - 1):
        start, end = int(slice_points[i]), int(slice_points[i + 1])
        if end > start:
            slices.append(y[start:end])
    # Tail
    if slice_points[-1] < len(y):
        slices.append(y[int(slice_points[-1]):])

    _prog(0.60, "Processing slices…")
    # 4. Per-slice transformations.
    processed: list[np.ndarray] = []
    n_slices = len(slices)
    for idx, s in enumerate(slices):
        if len(s) < 4:
            continue

        # Envelope (anti-click or crossfade).
        s = apply_envelope(s, sr, envelope_ms)

        # Random reverse
        if reverse_chance > 0 and random.random() < reverse_chance:
            s = s[::-1].copy()

        # Stutter / repeat
        # Two modes controlled by stutter_skip_ms:
        #   skip_ms == 0  →  Classic: tile the full slice (original behavior).
        #   skip_ms  > 0  →  Skip: loop only the head of the slice (stutter-edit
        #                    style). stutter_spread varies the head length
        #                    per-event for an organic, varied texture.
        if stutter_chance > 0 and random.random() < stutter_chance:
            actual_reps = random.randint(2, max(2, int(stutter_max_reps)))
            if stutter_skip_ms > 0:
                # Determine effective head length for this stutter event.
                if stutter_spread > 0:
                    lo_ms = max(5.0, stutter_skip_ms * (1.0 - float(stutter_spread)))
                    eff_ms = random.uniform(lo_ms, stutter_skip_ms)
                else:
                    eff_ms = float(stutter_skip_ms)
                head_n = max(int(sr * 0.005), int(sr * eff_ms / 1000.0))
                head_n = min(head_n, len(s))
                # Apply envelope to the head independently so each repeat
                # starts and ends cleanly rather than clicking mid-tile.
                head = apply_envelope(s[:head_n], sr, envelope_ms)
                s = np.tile(head, actual_reps)
            else:
                # Classic: tile the full slice.
                s = np.tile(s, actual_reps)

        processed.append(s)
        # Report slice progress between 0.60 and 0.80
        _prog(0.60 + 0.20 * (idx + 1) / max(n_slices, 1), "Processing slices…")

    _prog(0.82, "Mixing…")
    # 5. Optional global shuffle — controlled by the "randomize slice order"
    # checkbox uniformly across all modes. (When MAX RANDOM is selected in
    # the UI, a .change() handler auto-checks this box; user can uncheck it
    # to get random durations in original order.)
    if randomize_order:
        random.shuffle(processed)

    # 6. Concatenate and normalize.
    if not processed:
        out = y
    else:
        out = np.concatenate(processed)

    # Soft normalize to -1 dBFS to avoid clipping after stutter pile-up.
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0:
        out = (out / peak * 0.891).astype(np.float32)  # -1 dBFS

    _prog(0.92, "Encoding…")
    result = _write_audio(out, sr, output_format)
    _prog(1.0, "Done ✓")
    return result


# ---------------------------------------------------------------------------
# Output format helpers
# ---------------------------------------------------------------------------

# Formats soundfile can encode directly (no ffmpeg needed)
_SF_FORMATS = {
    "wav":  {"suffix": ".wav",  "subtype": "PCM_16"},
    "flac": {"suffix": ".flac", "subtype": "PCM_16"},
    "ogg":  {"suffix": ".ogg",  "subtype": "VORBIS"},
    "aiff": {"suffix": ".aiff", "subtype": "PCM_16"},
}

# Formats that require ffmpeg encoding (write wav first, then transcode)
_FFMPEG_FORMATS = {
    "mp3":  {"suffix": ".mp3",  "codec": "libmp3lame",  "quality": ["-q:a", "2"]},
    "aac":  {"suffix": ".m4a",  "codec": "aac",         "quality": ["-b:a", "192k"]},
}


def _write_audio(y: np.ndarray, sr: int, fmt: str) -> str:
    """Write audio array to a temp file in the requested format.

    Supports WAV/FLAC/OGG/AIFF via soundfile and MP3/AAC via bundled ffmpeg.
    Falls back to WAV if the format is unrecognised.
    """
    fmt = fmt.lower()

    if fmt in _SF_FORMATS:
        cfg = _SF_FORMATS[fmt]
        path = _new_temp_path(suffix=cfg["suffix"])
        sf.write(path, y, sr, subtype=cfg["subtype"])
        return path

    if fmt in _FFMPEG_FORMATS:
        cfg = _FFMPEG_FORMATS[fmt]
        # Step 1: write a temp WAV (lossless intermediate)
        wav_path = _new_temp_path(suffix=".wav", prefix="slurmify_tmp_")
        sf.write(wav_path, y, sr, subtype="PCM_16")

        # Step 2: locate ffmpeg (should be on PATH from bootstrap)
        import subprocess
        ffmpeg_exe = shutil.which("ffmpeg") or os.environ.get("FFMPEG_BINARY", "ffmpeg")

        out_path = _new_temp_path(suffix=cfg["suffix"])
        try:
            subprocess.run(
                [ffmpeg_exe, "-y", "-i", wav_path,
                 "-c:a", cfg["codec"], *cfg["quality"],
                 out_path],
                check=True,
                capture_output=True,
            )
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        return out_path

    # Unknown format — fall back to WAV
    return _write_audio(y, sr, "wav")


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Initialization JavaScript — runs after Gradio/Svelte page load.
# gr.Blocks(js=...) is the only reliable way to inject JS in Gradio 5;
# <script> tags inside gr.HTML use innerHTML injection and are silently
# ignored by modern browsers (DOM security policy).
# ---------------------------------------------------------------------------

# ── Static browser assets — JS, CSS, base64 images ───────────────────────────
# All browser-side content (INIT_JS, CUSTOM_CSS, GIF Easter eggs, icon) lives
# in ui_assets.py.  Splitting it out keeps app.py focused on Python logic and
# lets each asset file be edited with proper syntax highlighting.
# See ui_assets.py for the full explanation of each variable and why the GIF
# vars and CSS blocks are interleaved in that file.
# PYINSTALLER: "ui_assets" must stay in hiddenimports in slurmify.spec — it
# is not auto-detected because it is a local module with no C extension.
from ui_assets import (
    INIT_JS,        # ~500 lines of browser JS — Web Audio chain, FX param sync,
                    # hover gifs, favicon injection, keyboard shortcuts
    CUSTOM_CSS,     # ~1 200 lines of Gradio CSS — dark theme, chip-row radios,
                    # Easter egg ::after animations (Max, Bob, Hoberman-Max)
    _MAX_GIF_B64,   # base64 GIF: Max the tester (MAX RANDOM hover Easter egg)
    _BOB_GIF_B64,   # base64 GIF: Bob (reveal-temp-files button Easter egg)
    _HOBERMAN_GIF_B64,  # base64 GIF: Hoberman-Max (🎲 randomise-all Easter egg)
    _ICON_B64,      # base64 PNG: Subvoyant cat icon (favicon + header logo)
    _ICON_TAG,      # pre-assembled <a><img></a> HTML for the clickable header logo
)



# ── Audio Effects DSP (numpy/scipy — no extra deps) ─────────────────────────
# These match the Web Audio API chain so "burn FX" sounds like the preview.

def _fx_distortion(y: np.ndarray, drive: float) -> np.ndarray:
    """Tanh soft-clip waveshaper. drive 0-1 → pre-gain 1x-30x."""
    if drive < 0.01:
        return y
    k = float(1.0 + drive * 29.0)
    return (np.tanh(y * k) / np.tanh(k)).astype(np.float32)


def _fx_ring_mod(y: np.ndarray, sr: int, freq: float, depth: float) -> np.ndarray:
    """Amplitude modulation via carrier oscillator. depth 0-1."""
    if depth < 0.01:
        return y
    mono = y.ndim == 1
    if mono:
        y = y[np.newaxis, :]
    t = np.arange(y.shape[1], dtype=np.float32) / sr
    # gain = 1 + depth * sin(...) — matches Web Audio: gain.value=1, osc→gain
    mod = 1.0 + depth * np.sin(2 * np.pi * freq * t, dtype=np.float32)
    out = (y * mod[np.newaxis, :]).astype(np.float32)
    return out[0] if mono else out


def _fx_delay(y: np.ndarray, sr: int, delay_sec: float,
              feedback: float, mix: float) -> np.ndarray:
    """Tape delay with feedback loop. delay_sec 0-1s, feedback 0-0.9, mix 0-1."""
    if mix < 0.01 or delay_sec < 0.001:
        return y
    mono = y.ndim == 1
    if mono:
        y = y[np.newaxis, :]
    n_ch, n = y.shape
    d = max(1, int(delay_sec * sr))
    buf = np.zeros((n_ch, d), dtype=np.float32)
    wet = np.zeros_like(y)
    wi = 0
    for i in range(n):
        tap = buf[:, wi].copy()
        wet[:, i] = tap
        buf[:, wi] = y[:, i] + tap * feedback
        wi = (wi + 1) % d
    out = (y * (1 - mix) + wet * mix).astype(np.float32)
    return out[0] if mono else out


def _fx_phaser(y: np.ndarray, sr: int, rate: float, depth: float) -> np.ndarray:
    """4-stage allpass phaser with LFO. rate Hz, depth 0-1."""
    if depth < 0.01:
        return y
    from scipy.signal import lfilter
    mono = y.ndim == 1
    if mono:
        y = y[np.newaxis, :]
    n_ch, n = y.shape
    t = np.arange(n, dtype=np.float64) / sr
    lfo = np.sin(2 * np.pi * rate * t)          # -1..1
    # 4 allpass stages; LFO sweeps center freq ±(depth*50%) around each
    centers = [200.0, 600.0, 1200.0, 2400.0]
    phased = y.astype(np.float64).copy()
    for fc in centers:
        fc_mean = float(np.clip(fc * (1.0 + 0.5 * depth * lfo.mean()),
                                20, sr / 2 - 1))
        tw = np.tan(np.pi * fc_mean / sr)
        a = (tw - 1.0) / (tw + 1.0)
        for ch in range(n_ch):
            phased[ch] = lfilter([a, 1.0], [1.0, a], phased[ch])
    out = (y * (1 - depth * 0.5) + phased * (depth * 0.5)).astype(np.float32)
    return out[0] if mono else out


def burn_fx(
    audio_path,
    dist_drive, ring_freq, ring_depth,
    delay_sec, delay_fb, delay_mix,
    phase_rate, phase_depth,
    out_fmt,
):
    """Bake current FX settings into the output audio and return a new file."""
    if not audio_path or not os.path.exists(str(audio_path)):
        raise gr.Error("Run slurmify first — no output to apply FX to.")
    y, sr = librosa.load(audio_path, sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]
    y = y.astype(np.float32)

    y = _fx_distortion(y, float(dist_drive or 0))
    y = _fx_ring_mod(y, sr, float(ring_freq or 200), float(ring_depth or 0))
    y = _fx_delay(y, sr, float(delay_sec or 0.3),
                  float(delay_fb or 0.35), float(delay_mix or 0))
    y = _fx_phaser(y, sr, float(phase_rate or 1.0), float(phase_depth or 0))

    peak = float(np.max(np.abs(y)))
    if peak > 1.0:
        y = y / peak * 0.95
    y = np.clip(y, -1.0, 1.0)
    export = y[0] if y.shape[0] == 1 else y
    return _write_audio(export, sr, (out_fmt or "wav").lower())


# ── Video export (YouTube-ready MP4) ────────────────────────────────────────
# The 16:9 1.5-second loop animation lives pre-encoded as a 1920x1080
# H.264 MP4 (assets/siebaSlurm_A003.mp4) so that render time is dominated
# by the AAC audio encode and the video can be stream-copied — about 100x
# faster than re-decoding the original PNG sequence every loop pass.
# Branding (SUBVOYANT SIENA SLURMIFY title, www.subvoyant.com URL) is
# baked into the source frames; no separate bug overlay.
# To regenerate the loop file from the source PNGs in graphic/:
#   ffmpeg -framerate 12 -i graphic/siebaSlurm_A003/siebaSlurm_A003_%05d.png \
#          -vf "scale=1280:720:flags=lanczos,format=yuv420p" \
#          -c:v libx264 -preset slow -crf 30 -movflags +faststart -an \
#          assets/siebaSlurm_A003.mp4
# Notes:
#   -framerate 12 → 12 fps is the classic Disney "animation on twos"
#                   cell-animation rate. 36 source PNGs at 12 fps =
#                   3.0 s loop (half speed of the 24 fps source).
#   No fps filter → output container runs at the same 12 fps; no
#                   duplicate frames or rate conversion.
#   crf 30        → the chromatic-aberration borders absorb artifacts.
#   Source frames are 720p so we don't upscale — YouTube re-encodes
#   everything anyway. Output stream-copied: ~35 MB for a 3-minute song.
#
# Filename pattern:  Subvoyant_Siena_Slurmify_<title>_<jumble>.mp4
# The jumble is a slurm-style anagram of the source basename: shuffled, then
# look-alikes randomly transposed (e↔3, s↔5, o↔0, i↔1) at 50% probability.
# Capped at 16 chars for sane filenames; rich detail lives in MP4 metadata.

__version__ = "0.1.3"

_LEET_PAIRS = {
    "e": "3", "3": "e",
    "s": "5", "5": "s",
    "o": "0", "0": "o",
    "i": "1", "1": "i",
}


def _leetify(chars: list[str], rng: random.Random, prob: float = 0.5) -> list[str]:
    """Randomly transpose look-alike letter/digit pairs in a char list."""
    return [_LEET_PAIRS[c] if (c in _LEET_PAIRS and rng.random() < prob) else c
            for c in chars]


def _jumble_name(src_path: str, *, length: int = 16,
                 seed: int | None = None) -> str:
    """Slurm the source filename into a chaotic suffix.

    Drops extension and punctuation, lowercases, shuffles, leet-transposes,
    pads with random alphanumerics if too short, and trims to `length`.
    Deterministic when `seed` is given so a fixed slurmify seed reproduces
    the same suffix; freshly random otherwise.
    """
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
    """Sanitize a user-typed title for use in a filename."""
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


def render_video(
    slurm_audio_path: str,
    fx_audio_path: str | None,
    audio_source_label: str,                # "slurm output" | "FX-burned output"
    title_text: str,
    creator_text: str,
    include_source_filename: bool,
    # Slurmify params (for metadata blob) ─────────────────────────────────
    src_input_path: str,
    speed, resolution, transient_sensitivity, envelope_ms,
    preserve_pitch, pitch_shift_semitones,
    randomize_order, reverse_chance, stutter_chance,
    stutter_skip_ms, stutter_max_reps, stutter_spread,
    bpm_override_text,
    seed_text,
    # FX params (for metadata blob) ────────────────────────────────────────
    dist_drive, ring_freq, ring_depth,
    delay_time, delay_fb, delay_mix,
    phase_rate, phase_depth,
):
    """Render a YouTube-ready MP4 (1920x1080) from the slurm output.

    Returns the path to the rendered MP4. Audio is taken from either the
    raw slurm output or the FX-burned file based on `audio_source_label`.
    """
    import json
    import shutil
    import subprocess
    from datetime import datetime, timezone

    # Validate the dry slurm output exists no matter what — it's the floor
    # we either render directly OR auto-burn FX onto.
    if not slurm_audio_path or not os.path.exists(str(slurm_audio_path)):
        raise gr.Error("Run slurmify first — no audio to render.")

    # Pick the audio source.
    # Previous logic was `fx_audio_path or slurm_audio_path` — a silent
    # footgun: if user picked "FX-burned output" but never clicked the
    # "burn FX to file" button, fx_audio_path is None and the video would
    # render the DRY slurm output with no warning. Now we auto-burn from
    # the current slider values when needed, and print which path was used.
    if audio_source_label == "FX-burned output":
        if fx_audio_path and os.path.exists(str(fx_audio_path)):
            audio_path = fx_audio_path
            print(f"[slurm] video: using existing FX-burned audio → {audio_path}")
        else:
            print("[slurm] video: 'FX-burned output' selected but no burn "
                  "file exists — auto-burning FX from current slider values")
            audio_path = burn_fx(
                slurm_audio_path,
                dist_drive, ring_freq, ring_depth,
                delay_time, delay_fb, delay_mix,
                phase_rate, phase_depth,
                "wav",  # lossless intermediate; ffmpeg re-encodes to AAC anyway
            )
            print(f"[slurm] video: auto-burned FX → {audio_path}")
    else:
        audio_path = slurm_audio_path
        print(f"[slurm] video: using dry slurm audio → {audio_path}")

    # Resolve the looping animation. Pre-encoded as a 1.5 s H.264 MP4 at
    # 1920x1080 yuv420p so we can stream-copy it (no re-encoding) at
    # render time — that's the difference between ~180× realtime renders
    # and ~30× SLOWER than realtime renders we'd get from re-decoding the
    # original PNG sequence on every loop pass.
    loop_path = _asset("assets/siebaSlurm_A003.mp4")
    if not os.path.exists(loop_path):
        raise gr.Error(
            "Missing animation loop — assets/siebaSlurm_A003.mp4 not found."
        )

    # Parse seed (string from textbox)
    try:
        seed_int = int(seed_text) if seed_text and str(seed_text).strip() else None
    except (TypeError, ValueError):
        seed_int = None

    # Build filename: Subvoyant_Siena_Slurmify_<title>_<jumble>.mp4
    safe_title = _safe_title(title_text or "")
    jumble = _jumble_name(src_input_path or "untitled", length=16, seed=seed_int)
    parts = ["Subvoyant_Siena_Slurmify"]
    if safe_title:
        parts.append(safe_title)
    parts.append(jumble)
    fname = "_".join(parts) + ".mp4"

    out_path = _new_temp_path(suffix=f"_{fname}", prefix="slurmvid_")

    # Build the patch JSON for the metadata description.
    patch = {
        "version": __version__,
        "source": (Path(src_input_path).name
                   if (src_input_path and include_source_filename) else None),
        "seed": seed_int,
        "core": {
            "speed":                 float(speed) if speed is not None else None,
            "resolution":            resolution,
            "transient_sensitivity": float(transient_sensitivity)
                                     if transient_sensitivity is not None else None,
            "envelope_ms":           float(envelope_ms) if envelope_ms is not None else None,
            "preserve_pitch":        bool(preserve_pitch),
            "pitch_shift_semitones": float(pitch_shift_semitones)
                                     if pitch_shift_semitones is not None else 0.0,
            "randomize_order":       bool(randomize_order),
            "reverse_chance":        float(reverse_chance) if reverse_chance is not None else 0.0,
            "stutter_chance":        float(stutter_chance) if stutter_chance is not None else 0.0,
            "stutter_skip_ms":       float(stutter_skip_ms) if stutter_skip_ms is not None else 0.0,
            "stutter_max_reps":      int(stutter_max_reps) if stutter_max_reps is not None else 4,
            "stutter_spread":        float(stutter_spread) if stutter_spread is not None else 0.0,
            "bpm_override":          (float(bpm_override_text)
                                      if bpm_override_text and str(bpm_override_text).strip()
                                      else None),
        },
        "fx": {
            "dist_drive":  float(dist_drive  or 0),
            "ring_freq":   float(ring_freq   or 200),
            "ring_depth":  float(ring_depth  or 0),
            "delay_time":  float(delay_time  or 0.3),
            "delay_fb":    float(delay_fb    or 0.35),
            "delay_mix":   float(delay_mix   or 0),
            "phase_rate":  float(phase_rate  or 1.0),
            "phase_depth": float(phase_depth or 0),
        },
        "audio_source": audio_source_label,
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    patch_blob = json.dumps(patch, separators=(",", ":"))

    title_for_meta = (title_text or "").strip() or f"Subvoyant Slurm {jumble}"
    creator_for_meta = (creator_text or "").strip() or "Subvoyant SIENA Slurmer"
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
        "copyright":    f"Slurm rendering © {year}; "
                        "original audio © its respective owner.",
    }

    ffmpeg_exe = shutil.which("ffmpeg") or os.environ.get("FFMPEG_BINARY", "ffmpeg")

    # Stream-copy the pre-encoded loop video with -c:v copy. The loop file
    # is already at 1920x1080 yuv420p H.264, so ffmpeg only has to remux
    # video packets while encoding the audio track. This is dramatically
    # faster than re-encoding from PNGs every loop pass — roughly 100x
    # faster than realtime on modern hardware.
    cmd = [
        ffmpeg_exe, "-y",
        # input 0: pre-encoded loop, repeated to cover the audio duration
        "-stream_loop", "-1", "-i", loop_path,
        # input 1: audio
        "-i", str(audio_path),
        # video: stream-copy (no re-encode); audio: AAC for YouTube
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-shortest",
    ]
    for k, v in metadata.items():
        cmd += ["-metadata", f"{k}={v}"]
    cmd.append(out_path)

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Surface the last few lines of stderr so the UI shows a useful hint.
        err = (e.stderr or b"").decode(errors="replace").splitlines()
        tail = "\n".join(err[-12:]) if err else "(no ffmpeg stderr)"
        raise gr.Error(f"Video render failed.\n{tail}")

    return out_path


# ─────────────────────────────────────────────────────────────────────────────

def process(
    audio_file,
    speed,
    resolution,
    transient_sensitivity,
    envelope_ms,
    preserve_pitch,
    pitch_shift_semitones,
    randomize_order,
    reverse_chance,
    stutter_chance,
    stutter_skip_ms,
    stutter_max_reps,
    stutter_spread,
    bpm_override_text,
    output_format,
    start_sec,
    end_sec,
    seed_text,
    progress=gr.Progress(),
):
    if audio_file is None:
        raise gr.Error("Drop in an audio file first.")
    ext = Path(audio_file).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise gr.Error(f"Unsupported format: {ext}. Try one of: {sorted(SUPPORTED_EXTS)}")

    seed = None
    if seed_text and str(seed_text).strip():
        try:
            seed = int(seed_text)
        except ValueError:
            seed = None

    try:
        # Parse BPM override — accept blank or non-numeric as None.
        bpm_ov = None
        if bpm_override_text and str(bpm_override_text).strip():
            try:
                bpm_ov = float(bpm_override_text)
                if bpm_ov <= 0:
                    bpm_ov = None
            except (ValueError, TypeError):
                bpm_ov = None

        return slurmify(
            input_path=audio_file,
            speed=speed,
            resolution=resolution,
            transient_sensitivity=transient_sensitivity,
            envelope_ms=envelope_ms,
            preserve_pitch=preserve_pitch,
            pitch_shift_semitones=pitch_shift_semitones,
            randomize_order=randomize_order,
            reverse_chance=reverse_chance,
            stutter_chance=stutter_chance,
            stutter_skip_ms=float(stutter_skip_ms or 0),
            stutter_max_reps=int(stutter_max_reps or 4),
            stutter_spread=float(stutter_spread or 0),
            bpm_override=bpm_ov,
            start_sec=float(start_sec or 0),
            end_sec=float(end_sec or 0),
            output_format=output_format,
            seed=seed,
            _progress=progress,
        )
    except ValueError as e:
        raise gr.Error(str(e))


def _quit_app():
    """Shut down the server process cleanly from the browser UI.

    A short timer lets Gradio flush the response before os._exit fires,
    so the user sees the confirmation toast rather than a connection error.
    """
    import threading
    threading.Timer(0.8, lambda: os._exit(0)).start()
    return gr.Info("Shutting down — you can close this tab.")




def build_ui() -> gr.Blocks:

    # theme and css moved to launch() for Gradio 6 compatibility
    with gr.Blocks(title="Subvoyant SIENA Slurmer") as demo:
        gr.HTML(
            """
            <div class="slurm-header">
              """ + _ICON_TAG + """
              <div class="slurm-header-text">
                <h1 class="slurm-title"><a href="https://www.subvoyant.com" target="_blank" rel="noopener noreferrer" class="slurm-header-link">SIENA SLURMER</a></h1>
                <div class="slurm-tag">subvoyant · chopped · sped-up · transient-sliced · v0.1.3</div>
              </div>
              <div class="slurm-skin-wrap">
                <label for="slurm-skin-picker">skin</label>
                <select id="slurm-skin-picker"
                        onchange="window.slurmSetSkin && window.slurmSetSkin(this.value)">
                  <option value="default">subvoyant · default</option>
                  <option value="acid">acid cathedral</option>
                  <option value="hardware">hardware rack</option>
                </select>
              </div>
            </div>
            """
        )
        gr.Markdown(
            "Drop in **any audio or video file** below. Twist knobs. Get slurm. "
            "Audio is extracted automatically from video — mp3, wav, flac, mp4, mov, mkv, etc."
        )

        with gr.Row():
            with gr.Column(scale=1):
                # ── Universal upload — accepts ANY audio or video file ───
                # gr.Audio's MIME validation rejects video/* uploads server-side
                # regardless of what the browser file picker shows. To make
                # "drop any file" actually work, the primary upload is a
                # gr.File (no MIME filtering); a change handler routes audio
                # files through directly and runs ffmpeg on video files to
                # extract their audio track. The result populates audio_in
                # below — which only becomes visible AFTER a file is loaded,
                # so there's no chance of dropping on the wrong target.
                media_file_in = gr.File(
                    label="🎵📹 drop ANY audio or video file here",
                    file_count="single",
                    type="filepath",
                    file_types=None,  # accept anything
                    elem_id="slurm-media-file",
                    elem_classes=["slurm-media-file"],
                )

                audio_in = gr.Audio(
                    label="input audio",
                    type="filepath",
                    sources=["upload"],
                    elem_classes=["slurm-audio"],
                    visible=False,  # hidden until upload handler populates it
                )

                # ── In/Out bar ─────────────────────────────────────────
                # Real Gradio buttons + fn=None,js= is the only reliable
                # way to read audio.currentTime into Gradio state in Gradio 5.
                # (Scripts inside gr.HTML use innerHTML injection and are
                #  silently ignored by modern browsers.)
                # Clock + keyboard shortcuts live in INIT_JS (gr.Blocks(js=...)).
                with gr.Row(elem_id="slurm-inout-bar"):
                    gr.HTML('<div id="slurm-clock-wrap">► 0:00.00</div>')
                    in_btn    = gr.Button("[ I ] in",  elem_id="slurm-in-btn",
                                          elem_classes=["slurm-io-btn"], size="sm")
                    out_btn   = gr.Button("[ O ] out", elem_id="slurm-out-btn",
                                          elem_classes=["slurm-io-btn"], size="sm")
                    clear_btn = gr.Button("✕ clear",   elem_id="slurm-clear-btn",
                                          elem_classes=["slurm-io-btn", "slurm-io-clear"], size="sm")

                # ── Utility bar — randomize all + reveal temp files ──────
                # The randomize button gets the same Max-gif hover treatment
                # as MAX RANDOM (slurm-max-option class) — both are "Max-the-
                # tester chaos" features. Reveal opens SESSION_TMP_DIR in
                # the OS file browser so users can see / save outputs before
                # the session ends and the dir gets wiped on quit.
                with gr.Row(elem_id="slurm-util-bar"):
                    randomize_all_btn = gr.Button(
                        "🎲 randomize all",
                        elem_id="slurm-randomize-btn",
                        elem_classes=["slurm-io-btn", "slurm-max-popup"],
                        size="sm",
                    )
                    reveal_tmp_btn = gr.Button(
                        "📁 reveal temp files",
                        elem_id="slurm-reveal-btn",
                        elem_classes=["slurm-io-btn", "slurm-bob-option"],
                        size="sm",
                    )

                with gr.Row():
                    start_sec = gr.Textbox(
                        label="in (sec)",
                        value="0",
                        elem_id="start-sec-box",
                        info="0 = from start",  # matched info= → same DOM as out
                        max_lines=1,
                    )
                    end_sec = gr.Textbox(
                        label="out (sec)",
                        value="0",
                        elem_id="end-sec-box",
                        info="0 = full file",
                        max_lines=1,
                    )

                speed = gr.Slider(
                    label="speed multiplier",
                    minimum=0.05, maximum=4.0, step=0.05, value=2.0,
                    info="< 1.0 = slower · 1.0 = original speed · > 1.0 = faster",
                )
                resolution = gr.Radio(
                    label="slice resolution",
                    choices=["1/1", "1/2", "1/4", "1/8", "1/16", "1/32", "1/64", "1/128", "MAX RANDOM"],
                    value="1/16",
                    info=("grid spacing for slices, in note values · "
                          "MAX RANDOM bypasses the grid (auto-checks shuffle)"),
                )
                bpm_override = gr.Textbox(
                    label="BPM override (optional)",
                    placeholder="leave blank for auto-detect",
                    info="set if the tempo sounds off — e.g. enter 140 if librosa detected 70",
                    max_lines=1,
                )
                transient_sensitivity = gr.Slider(
                    label="transient sensitivity",
                    minimum=0.0, maximum=1.0, step=0.05, value=0.5,
                    info="0 = pure tempo grid · 1 = follow onsets exactly",
                )
                envelope_ms = gr.Slider(
                    label="slice envelope (ms)",
                    minimum=0.0, maximum=20.0, step=0.5, value=2.0,
                    info="0 = hard cuts (clicky, classic) · higher = smoother",
                )

            with gr.Column(scale=1):
                preserve_pitch = gr.Checkbox(
                    label="preserve pitch when speeding up",
                    value=True,
                    info="off = chipmunk effect (pitch rises with speed)",
                )
                pitch_shift_semitones = gr.Slider(
                    label="pitch shift (semitones)",
                    minimum=-24, maximum=24, step=1, value=0,
                    info="−24 = 2 octaves down · 0 = no change · +24 = 2 octaves up",
                )
                randomize_order = gr.Checkbox(
                    label="randomize slice order",
                    value=False,
                )
                reverse_chance = gr.Slider(
                    label="reverse chance per slice",
                    minimum=0.0, maximum=1.0, step=0.05, value=0.0,
                    info="probability each slice plays backwards",
                )
                stutter_chance = gr.Slider(
                    label="stutter chance per slice",
                    minimum=0.0, maximum=1.0, step=0.05, value=0.15,
                    info="probability each slice is stuttered",
                )
                stutter_skip_ms = gr.Slider(
                    label="skip length (ms)",
                    minimum=0.0, maximum=100.0, step=1.0, value=0.0,
                    info="0 = full-slice repeat (classic) · 20–40 ms = CD-skip · 5–15 ms = glitch buzz",
                )
                stutter_max_reps = gr.Slider(
                    label="reps (max)",
                    minimum=2, maximum=16, step=1, value=4,
                    info="upper bound for repeat count — draw is random 2 → max",
                )
                stutter_spread = gr.Slider(
                    label="spread",
                    minimum=0.0, maximum=1.0, step=0.05, value=0.0,
                    info="0 = uniform skip length · 1 = each stutter picks its own random length",
                )
                seed_text = gr.Textbox(
                    label="seed (optional)",
                    placeholder="leave blank for random",
                    info="set a number for reproducible output",
                    elem_id="slurm-seed-box",
                    max_lines=1,
                )
                output_format = gr.Dropdown(
                    label="output format",
                    choices=["wav", "mp3", "flac", "ogg", "aiff"],
                    value="wav",
                    info="wav/flac/ogg/aiff are lossless or open; mp3 uses bundled ffmpeg",
                    elem_classes=["slurm-dropdown"],
                )

                go_btn = gr.Button("⟶ slurmify", variant="primary", size="lg")
                # Acid skin reads/positions this absolute halo behind go_btn.
                gr.HTML('<div id="slurm-go-halo"></div>')
                quit_btn = gr.Button("⏻ quit app", variant="stop", size="sm")

        # Loading animation — hidden until processing starts
        _gif_path = _asset("assets/siena_dancer.gif")
        with gr.Row():
            dancer = gr.Image(
                value=_gif_path if os.path.exists(_gif_path) else None,
                label=None,
                show_label=False,
                visible=False,
                container=False,
                elem_id="siena-dancer",
                width=200,
            )

        audio_out = gr.Audio(label="output", type="filepath",
                             elem_id="slurm-audio-out",
                             elem_classes=["slurm-audio", "slurm-audio-output"])

        # VU meter canvas — visible only in hardware skin (CSS-gated).
        # The init JS taps the FX chain's analyser and draws RMS bars here.
        gr.HTML('<canvas id="slurm-vu-meter" width="800" height="28"></canvas>')

        # Mirror Gradio's slurm output URL into the FX preview <audio> element
        # whenever audio_out's value changes. fn=None + js= runs purely on the
        # frontend (no Python round-trip). Gradio passes the audio's FileData
        # — which has a frontend-resolvable .url for the served file — so we
        # don't have to scrape Gradio's WaveSurfer DOM for it.
        audio_out.change(
            fn=None,
            inputs=[audio_out],
            outputs=[],
            js="""(d) => {
                console.log('[slurm] audio_out.change payload:', d);
                const fx = document.getElementById('slurm-fx-audio');
                if (!fx) { console.log('[slurm] FX preview element not found'); return; }
                let url = '';
                if (d) {
                    if (typeof d === 'string') {
                        url = d.startsWith('http') || d.startsWith('/')
                            ? d : '/gradio_api/file=' + d;
                    } else if (d.url) {
                        url = d.url;
                    } else if (d.path) {
                        url = '/gradio_api/file=' + d.path;
                    } else if (d.value) {
                        // Some Gradio versions wrap the value
                        const v = d.value;
                        if (typeof v === 'string') url = v;
                        else if (v && v.url) url = v.url;
                        else if (v && v.path) url = '/gradio_api/file=' + v.path;
                    }
                }
                console.log('[slurm] audio_out.change resolved URL:', url);
                if (url && fx.src !== url) {
                    fx.src = url;
                    try { fx.load(); } catch(e) {}
                } else if (!d) {
                    fx.removeAttribute('src');
                    try { fx.load(); } catch(e) {}
                }
            }""",
        )

        # ── Auto-check shuffle when MAX RANDOM is selected ───────────────
        # Without shuffle, MAX RANDOM only randomizes positions but slices
        # still play in original order — sounds like "song with random fades"
        # rather than chaos. Auto-checking the box surfaces this in the UI;
        # user can override by manually unchecking it.
        def _on_resolution_change(res):
            if res == "MAX RANDOM":
                return gr.update(value=True)
            return gr.update()  # other modes: leave checkbox alone
        resolution.change(
            fn=_on_resolution_change,
            inputs=resolution,
            outputs=randomize_order,
        )

        # ── Randomize all slurm parameters ───────────────────────────────
        # Scrambles every parameter EXCEPT input audio, in/out trim, output
        # format, and seed (those are user choices that "randomize all"
        # shouldn't blow away). Ranges are biased toward musical-sounding
        # values rather than full extremes — e.g. speed in 0.5-3.0 rather
        # than 0.05-4.0, pitch shift weighted toward octaves and 5ths.
        def _randomize_all():
            import random as _r
            _RES_CHOICES = ["1/1", "1/2", "1/4", "1/8", "1/16",
                            "1/32", "1/64", "1/128", "MAX RANDOM"]
            new_res = _r.choice(_RES_CHOICES)
            print(f"[slurm] randomize all → resolution={new_res}")
            return {
                speed:                 round(_r.uniform(0.5, 3.0), 2),
                resolution:            new_res,
                transient_sensitivity: round(_r.random(), 2),
                envelope_ms:           round(_r.uniform(0.0, 8.0), 1),
                preserve_pitch:        _r.random() < 0.7,  # bias toward preserve
                # Weighted toward musically-meaningful intervals (octaves, 5ths)
                pitch_shift_semitones: _r.choice(
                    [-12, -7, -5, -3, 0, 0, 0, 3, 5, 7, 12]),
                randomize_order:       (new_res == "MAX RANDOM")
                                       or (_r.random() < 0.5),
                reverse_chance:        round(_r.uniform(0.0, 0.5), 2),
                stutter_chance:        round(_r.uniform(0.0, 0.5), 2),
                # Stutter engine — bias toward the interesting mid-ranges:
                # skip_ms: weight toward 0 (classic) and the skippy 15-40ms zone
                stutter_skip_ms:       float(_r.choice(
                    [0, 0, 0, 10, 15, 20, 25, 30, 40, 50])),
                stutter_max_reps:      int(_r.choice([2, 3, 4, 4, 6, 8])),
                stutter_spread:        round(_r.uniform(0.0, 0.6), 2),
            }
        randomize_all_btn.click(
            fn=_randomize_all,
            inputs=[],
            outputs=[speed, resolution, transient_sensitivity, envelope_ms,
                     preserve_pitch, pitch_shift_semitones, randomize_order,
                     reverse_chance, stutter_chance,
                     stutter_skip_ms, stutter_max_reps, stutter_spread],
        )

        # ── Reveal temp files in OS file browser ─────────────────────────
        reveal_tmp_btn.click(fn=_reveal_temp_dir, inputs=[], outputs=[])

        # ── Universal upload router → audio_in ───────────────────────────
        # The single drop zone (media_file_in) accepts ANY file. This handler
        # routes by file extension:
        #   • Audio file → pass the path through directly to audio_in
        #   • Video / other media → ffmpeg extracts the audio track to a
        #     session-temp wav, audio_in gets the extracted path
        # In both cases audio_in becomes VISIBLE so the waveform + transport
        # render. (audio_in starts visible=False so the page doesn't show
        # an empty audio component before any file is loaded.)
        _AUDIO_EXTS = {".mp3", ".wav", ".aif", ".aiff", ".aac", ".m4a",
                       ".flac", ".ogg", ".opus", ".wma", ".ape", ".alac"}
        def _route_upload(media_path):
            if not media_path:
                # Cleared — hide audio_in again
                return gr.update(value=None, visible=False)
            src = media_path if isinstance(media_path, str) else getattr(media_path, "name", str(media_path))
            ext = Path(src).suffix.lower()
            if ext in _AUDIO_EXTS:
                # Audio file — just pass through.
                print(f"[slurm] audio file uploaded: {src}")
                return gr.update(value=src, visible=True)
            # Non-audio (video / other media) — extract the audio track.
            print(f"[slurm] non-audio file uploaded — ffmpeg extracting: {src}")
            out_path = _new_temp_path(suffix=".wav", prefix="extracted_")
            import subprocess
            ffmpeg_exe = (shutil.which("ffmpeg")
                          or os.environ.get("FFMPEG_BINARY", "ffmpeg"))
            try:
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", src,
                     "-vn",                       # drop video stream
                     "-acodec", "pcm_s16le",      # 16-bit PCM wav
                     "-ar", "44100",              # match TARGET_SR
                     "-ac", "2",                  # stereo (load_audio mono-mixes later)
                     out_path],
                    check=True, capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                err_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
                print(f"[slurm] ffmpeg extraction failed: {err_tail}")
                raise gr.Error(f"Couldn't extract audio from that file. ffmpeg said: {err_tail[:200]}")
            print(f"[slurm] extracted → {out_path}")
            return gr.update(value=out_path, visible=True)
        media_file_in.change(
            fn=_route_upload,
            inputs=media_file_in,
            outputs=audio_in,
        )

        # Show dancer while processing, hide when done
        go_btn.click(
            fn=lambda: gr.Image(visible=True),
            inputs=[],
            outputs=dancer,
        ).then(
            fn=process,
            inputs=[
                audio_in, speed, resolution, transient_sensitivity,
                envelope_ms, preserve_pitch, pitch_shift_semitones,
                randomize_order, reverse_chance, stutter_chance,
                stutter_skip_ms, stutter_max_reps, stutter_spread,
                bpm_override,
                output_format, start_sec, end_sec, seed_text,
            ],
            outputs=audio_out,
        ).then(
            fn=lambda: gr.Image(visible=False),
            inputs=[],
            outputs=dancer,
        )

        # ── In/Out button handlers ────────────────────────────────────────────
        # fn=None with js= runs pure client-side JS and pipes the return value
        # directly into the output component — no Python round-trip.
        # INIT_JS (above) installs keyboard shortcut listeners that click these
        # same buttons so I/O key shortcuts update the same Textboxes.
        # ── In/Out button handlers ────────────────────────────────────────────
        # Each js= string MUST be a single callable function expression.
        # Gradio evaluates it and calls it; the return value updates outputs.
        # Concatenating a bare function declaration + arrow function is NOT valid
        # (the frontend sees two separate statements, not one callable) and causes
        # the Gradio page to freeze on "Loading...".
        # Gradio 6 js= on click handlers: MUST return an ARRAY matching outputs.
        # WaveSurfer embeds the <audio> element inside a Shadow DOM, so
        # document.querySelector('audio') always misses it.
        # We walk every shadow root to find it, and also read the on-screen
        # timestamp text as a fallback (WaveSurfer always keeps that up to date).
        _probe_fn = """() => {
            // 1. Walk all shadow roots to find every <audio> element.
            //    WaveSurfer v7 appends its media element inside a shadow root.
            var all = [];
            (function walk(root) {
                try {
                    root.querySelectorAll('audio').forEach(function(a) { all.push(a); });
                    root.querySelectorAll('*').forEach(function(el) {
                        if (el.shadowRoot) walk(el.shadowRoot);
                    });
                } catch(e) {}
            })(document);

            var best = null;
            all.forEach(function(a) {
                if (!best || a.currentTime > best.currentTime) best = a;
            });

            if (best && best.currentTime > 0) {
                return [best.currentTime.toFixed(2)];
            }

            // 2. Fallback: read the on-screen timestamp text that WaveSurfer
            //    updates via its timeupdate event.
            var stamps = document.querySelectorAll('.timestamps span, .timestamps div, [class*="timestamp"]');
            var parsed = 0;
            stamps.forEach(function(el) {
                var m2 = el.textContent.trim().match(/^(\\d+):(\\d+\\.?\\d*)$/);
                if (m2) {
                    var secs = parseInt(m2[1],10)*60 + parseFloat(m2[2]);
                    if (secs > parsed) parsed = secs;
                }
            });
            if (parsed > 0) return [parsed.toFixed(2)];

            // 3. Last resort: plain document audio (non-waveform player)
            var plain = document.querySelector('audio');
            return [String((plain ? plain.currentTime : 0).toFixed(2))];
        }"""

        _clear_js = "() => ['0', '0']"

        in_btn.click(fn=None, inputs=[], outputs=[start_sec], js=_probe_fn)
        out_btn.click(fn=None, inputs=[], outputs=[end_sec], js=_probe_fn)
        clear_btn.click(fn=None, inputs=[], outputs=[start_sec, end_sec], js=_clear_js)

        quit_btn.click(fn=_quit_app, inputs=[], outputs=[])

        # ── FX Panel ──────────────────────────────────────────────────────────
        # Real-time effects via Web Audio API (zero Python round-trip).
        # Sliders fire window.slurmFx.set*() directly via fn=None,js=.
        # "Burn FX" bakes current settings into a new file via Python DSP.
        with gr.Accordion("⚡ real-time FX", open=False,
                           elem_id="slurm-fx-panel"):

            with gr.Row():
                # ── Left col: Distortion + Ring Mod ─────────────────────────
                with gr.Column():
                    gr.HTML('<div class="slurm-fx-section">distortion</div>')
                    fx_dist = gr.Slider(
                        label="drive", minimum=0, maximum=1, step=0.01, value=0,
                        info="0 = clean · 1 = full saturation",
                    )
                    gr.HTML('<div class="slurm-fx-section">ring modulation</div>')
                    fx_ring_freq = gr.Slider(
                        label="carrier freq (Hz)", minimum=10, maximum=1000,
                        step=1, value=200,
                        info="frequency of the amplitude modulator oscillator",
                    )
                    fx_ring_depth = gr.Slider(
                        label="depth", minimum=0, maximum=1, step=0.01, value=0,
                        info="0 = dry · 1 = fully modulated",
                    )

                # ── Right col: Delay + Phaser ────────────────────────────────
                with gr.Column():
                    gr.HTML('<div class="slurm-fx-section">delay</div>')
                    fx_delay_time = gr.Slider(
                        label="time (s)", minimum=0.01, maximum=1.0,
                        step=0.01, value=0.3,
                        info="delay buffer length",
                    )
                    fx_delay_fb = gr.Slider(
                        label="feedback", minimum=0, maximum=0.9,
                        step=0.01, value=0.35,
                        info="how much of the delayed signal feeds back",
                    )
                    fx_delay_mix = gr.Slider(
                        label="mix", minimum=0, maximum=1, step=0.01, value=0,
                        info="0 = dry · 1 = fully wet",
                    )
                    gr.HTML('<div class="slurm-fx-section">phaser</div>')
                    fx_phase_rate = gr.Slider(
                        label="rate (Hz)", minimum=0.1, maximum=8,
                        step=0.1, value=1.0,
                        info="LFO speed sweeping the allpass filters",
                    )
                    fx_phase_depth = gr.Slider(
                        label="depth", minimum=0, maximum=1,
                        step=0.01, value=0,
                        info="0 = dry · 1 = full phase sweep",
                    )

            # ── Live FX preview ───────────────────────────────────────────
            # Dedicated <audio> element we fully own. The init JS mirrors
            # Gradio's output URL into this element, then routes it through
            # the Web Audio FX chain (createMediaElementSource is bound here
            # exactly once for the lifetime of the page). Hit play here to
            # hear the slurm output through the live distortion / ring mod /
            # delay / phaser chain — slider changes apply in real time.
            gr.HTML(
                """
                <div class="slurm-fx-section" style="margin-top:6px;">FX preview</div>
                <audio id="slurm-fx-audio" controls preload="auto"
                       style="width:100%; margin-top:4px;"></audio>
                <div class="info" style="margin-top:4px;">
                    plays the slurm output through the live FX chain ·
                    move the sliders above while it plays
                </div>
                """
            )

            with gr.Row():
                fx_out_fmt = gr.Dropdown(
                    choices=["wav", "flac", "mp3", "ogg", "aiff"],
                    value="wav", label="export format", scale=1,
                    elem_classes=["slurm-dropdown"],
                )
                burn_btn = gr.Button("⬇ burn FX to file", variant="primary",
                                     scale=3, elem_id="slurm-burn-btn")

            audio_out_fx = gr.Audio(label="output + FX", type="filepath",
                                    elem_classes=["slurm-audio", "slurm-audio-output"])

        # ── FX slider → Web Audio (no Python round-trip) ──────────────────
        _js = lambda fn: f"(v) => {{ window.slurmFx && window.slurmFx.{fn}(v); }}"
        fx_dist.change(fn=None, inputs=[fx_dist],
                       outputs=[], js=_js("setDist"))
        fx_ring_freq.change(fn=None, inputs=[fx_ring_freq],
                            outputs=[], js=_js("setRingFreq"))
        fx_ring_depth.change(fn=None, inputs=[fx_ring_depth],
                             outputs=[], js=_js("setRingDepth"))
        fx_delay_time.change(fn=None, inputs=[fx_delay_time],
                             outputs=[], js=_js("setDelayTime"))
        fx_delay_fb.change(fn=None, inputs=[fx_delay_fb],
                           outputs=[], js=_js("setDelayFb"))
        fx_delay_mix.change(fn=None, inputs=[fx_delay_mix],
                            outputs=[], js=_js("setDelayMix"))
        fx_phase_rate.change(fn=None, inputs=[fx_phase_rate],
                             outputs=[], js=_js("setPhaseRate"))
        fx_phase_depth.change(fn=None, inputs=[fx_phase_depth],
                              outputs=[], js=_js("setPhaseDepth"))

        # ── Burn FX: bake effects into a new file ─────────────────────────
        burn_btn.click(
            fn=burn_fx,
            inputs=[
                audio_out,
                fx_dist, fx_ring_freq, fx_ring_depth,
                fx_delay_time, fx_delay_fb, fx_delay_mix,
                fx_phase_rate, fx_phase_depth,
                fx_out_fmt,
            ],
            outputs=[audio_out_fx],
        )

        # ── Video export (YouTube-ready MP4) ──────────────────────────────
        # Looping dancer + slurm audio + subvoyant.com bug, with the slurm
        # patch parameters embedded in the MP4 metadata atoms (so YouTube
        # auto-fills title/description on upload, and the file is
        # self-describing for any future "import patch" feature).
        with gr.Accordion("🎬 export video for YouTube", open=False,
                          elem_id="slurm-video-panel"):
            with gr.Row():
                video_title   = gr.Textbox(
                    label="title (optional)",
                    placeholder="leave blank for an autogenerated name",
                    max_lines=1, scale=2,
                )
                video_creator = gr.Textbox(
                    label="creator (optional)",
                    placeholder="your name or handle",
                    max_lines=1, scale=2,
                )
            with gr.Row():
                video_source = gr.Radio(
                    choices=["slurm output", "FX-burned output"],
                    value="FX-burned output",
                    label="audio source",
                    info="which audio to render the video from",
                    scale=3,
                )
                include_source = gr.Checkbox(
                    label="include source filename in metadata",
                    value=False,
                    info="off keeps the patch JSON anonymous",
                    scale=2,
                )
            video_btn = gr.Button("🎥 render YouTube MP4",
                                  variant="primary",
                                  elem_id="slurm-video-btn")
            video_out = gr.Video(label="video preview", interactive=False,
                                 elem_id="slurm-video-out")

        video_btn.click(
            fn=render_video,
            inputs=[
                audio_out, audio_out_fx,
                video_source, video_title, video_creator, include_source,
                # slurmify params for metadata
                audio_in,
                speed, resolution, transient_sensitivity, envelope_ms,
                preserve_pitch, pitch_shift_semitones,
                randomize_order, reverse_chance, stutter_chance,
                stutter_skip_ms, stutter_max_reps, stutter_spread,
                bpm_override,
                seed_text,
                # FX params for metadata
                fx_dist, fx_ring_freq, fx_ring_depth,
                fx_delay_time, fx_delay_fb, fx_delay_mix,
                fx_phase_rate, fx_phase_depth,
            ],
            outputs=[video_out],
        )

        gr.Markdown(
            "<sub>processing is local — your audio never leaves your machine.</sub>"
        )

    return demo


if __name__ == "__main__":
    ui = build_ui()
    # Gradio 6: inject JS via head= as a real <script> tag.
    # launch(js=) and gr.Blocks(js=) are both unreliable in Gradio 6
    # (they use eval() which breaks on IIFEs in some versions).
    # head= injects raw HTML into <head>, so the browser executes the script normally.
    # Google Fonts for the alternate skins. Loaded for all skins (browser
    # caches them) but only referenced by the relevant [data-skin] CSS.
    #   Bagel Fat One       — acid title
    #   Major Mono Display  — hardware section headings
    #   Share Tech Mono     — hardware value readouts
    #   VT323               — hardware LCD-style numerals
    _fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" '
        'href="https://fonts.googleapis.com/css2?'
        'family=Bagel+Fat+One&'
        'family=Major+Mono+Display&'
        'family=Share+Tech+Mono&'
        'family=VT323&display=swap">'
    )
    # Browser tab icon — Siena cat. Multi-pronged attack:
    #   1. Write _ICON_B64 to a temp PNG, pass via favicon_path (Gradio's
    #      documented API; serves the file at /favicon.ico).
    #   2. Inject <link rel="icon"> tags at the END of head.
    #   3. JS-based setter that runs after page load AND re-applies on a
    #      timeout (defeats anything Gradio sets post-load). This is the
    #      one that actually wins — head-injected links and favicon_path
    #      both got overridden in testing.
    _favicon_path = _new_temp_path(suffix=".png", prefix="slurm-favicon-")
    with open(_favicon_path, "wb") as _f:
        _f.write(base64.b64decode(_ICON_B64))
    print(f"[slurm] favicon written to: {_favicon_path}")
    _favicon_links = (
        f'<link rel="icon" type="image/png" sizes="any" '
        f'href="data:image/png;base64,{_ICON_B64}">\n'
        f'<link rel="shortcut icon" type="image/png" '
        f'href="data:image/png;base64,{_ICON_B64}">\n'
        f'<link rel="apple-touch-icon" '
        f'href="data:image/png;base64,{_ICON_B64}">'
    )
    # JS-based favicon setter — purges existing icon links, appends ours.
    # Re-runs at multiple timeouts to defeat any post-load overrides.
    _favicon_js = (
        '<script>\n'
        '(function () {\n'
        '    function _slurmSetFavicon() {\n'
        '        var d = document;\n'
        '        var olds = d.querySelectorAll(\'link[rel*="icon"]\');\n'
        '        for (var i = 0; i < olds.length; i++) {\n'
        '            if (!olds[i].dataset.slurmFav) olds[i].parentNode.removeChild(olds[i]);\n'
        '        }\n'
        '        var l = d.createElement("link");\n'
        '        l.rel = "icon";\n'
        '        l.type = "image/png";\n'
        '        l.dataset.slurmFav = "1";\n'
        f'        l.href = "data:image/png;base64,{_ICON_B64}";\n'
        '        d.head.appendChild(l);\n'
        '        console.log("[slurm] favicon set via JS at " + Date.now());\n'
        '    }\n'
        '    if (document.readyState === "loading") {\n'
        '        document.addEventListener("DOMContentLoaded", _slurmSetFavicon);\n'
        '    } else {\n'
        '        _slurmSetFavicon();\n'
        '    }\n'
        '    // Re-apply after Gradio finishes its own DOM tinkering\n'
        '    setTimeout(_slurmSetFavicon, 500);\n'
        '    setTimeout(_slurmSetFavicon, 2000);\n'
        '    setTimeout(_slurmSetFavicon, 5000);\n'
        '})();\n'
        '</script>'
    )
    _head = (
        f"{_fonts}\n"
        f"<script>\n{INIT_JS}\n</script>\n"
        f"{_favicon_links}\n"
        f"{_favicon_js}"
    )

    ui.launch(
        inbrowser=True,          # auto-open browser tab (critical for the .app bundle)
        server_name="127.0.0.1",
        show_error=True,
        css=CUSTOM_CSS,
        head=_head,
        favicon_path=_favicon_path,
        theme=gr.themes.Base(
            primary_hue="cyan",
            neutral_hue="slate",
        ),
    )
