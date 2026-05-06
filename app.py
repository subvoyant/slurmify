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
INIT_JS = """
(function () {
    var _dbg = function(msg) { console.log('[SLURM] ' + msg); };

    _dbg('INIT_JS fired ✓');

    // ── Skin switcher ────────────────────────────────────────────────────
    // Three skins coexist in the CSS; only the one named in body[data-skin]
    // is visible. Order of precedence for picking the active skin:
    //   1. ?skin=<name> URL param
    //   2. localStorage 'slurm_skin'
    //   3. 'default'
    var _SKIN_NAMES = ['default', 'acid', 'hardware'];
    function _slurmSetSkin(name) {
        if (_SKIN_NAMES.indexOf(name) === -1) name = 'default';
        document.body.dataset.skin = name;
        try { localStorage.setItem('slurm_skin', name); } catch(e) {}
        var sel = document.getElementById('slurm-skin-picker');
        if (sel && sel.value !== name) sel.value = name;
        _dbg('skin → ' + name);
    }
    (function _slurmInitSkin() {
        var url   = new URL(window.location);
        var skin  = url.searchParams.get('skin');
        if (!skin) {
            try { skin = localStorage.getItem('slurm_skin'); } catch(e) {}
        }
        _slurmSetSkin(skin || 'default');
    })();
    window.slurmSetSkin = _slurmSetSkin;

    // ── Live playhead clock ──────────────────────────────────────────────
    var _clockTick = 0;
    (function tick() {
        var a = document.querySelector('audio');
        var c = document.getElementById('slurm-clock-wrap');
        if (c) {
            var t = (a && !isNaN(a.currentTime)) ? a.currentTime : 0;
            c.textContent = '► ' + Math.floor(t / 60) + ':'
                            + (t % 60).toFixed(2).padStart(5, '0');
        }
        _clockTick++;
        if (_clockTick === 1) _dbg('clock loop started, audio=' + (a ? 'found' : 'NOT FOUND'));
        if (_clockTick === 60) _dbg('clock @ 60 frames, clock-wrap=' + (c ? 'found' : 'NOT FOUND'));
        requestAnimationFrame(tick);
    })();

    // ── Keyboard shortcuts — I / O ─────────────────────────────────────
    // Gradio 6 applies elem_id directly to the <button> element itself,
    // NOT to a wrapper div. Try all selector forms + text-content fallback.
    function slurmFindBtn(id, text) {
        return document.querySelector('#' + id)
            || document.querySelector('#' + id + ' button')
            || Array.from(document.querySelectorAll('button')).find(function(b) {
                   return b.textContent.trim().indexOf(text) !== -1;
               });
    }
    document.addEventListener('keydown', function (e) {
        var tag = (e.target.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (e.key === 'i' || e.key === 'I') {
            e.preventDefault();
            var b = slurmFindBtn('slurm-in-btn', 'I ] in');
            _dbg('I key: btn=' + (b ? 'FOUND id=' + (b.id||'?') + ', clicking' : 'NOT FOUND'));
            if (b) b.click();
        }
        if (e.key === 'o' || e.key === 'O') {
            e.preventDefault();
            var b = slurmFindBtn('slurm-out-btn', 'O ] out');
            _dbg('O key: btn=' + (b ? 'FOUND id=' + (b.id||'?') + ', clicking' : 'NOT FOUND'));
            if (b) b.click();
        }
    });

    _dbg('keydown listener attached ✓');

    // ── Web Audio FX chain ───────────────────────────────────────────────
    // Inspired by: Sambego/audio-effects, noisehack.com, tomhazledine.com/web-audio-delay
    // Topology: src → distortion → ringMod → delay → phaser → destination
    var _fxCtx = null, _fxSrc = null, _fxN = null;
    var _fxP = {
        distDrive:  0,
        ringFreq:   200, ringDepth: 0,
        delayTime:  0.3, delayFb: 0.35, delayMix: 0,
        phaseRate:  1.0, phaseDepth: 0
    };

    function _fxWalk(root) {
        var found = [];
        try {
            root.querySelectorAll('audio').forEach(function(a) { found.push(a); });
            root.querySelectorAll('*').forEach(function(el) {
                if (el.shadowRoot) found = found.concat(_fxWalk(el.shadowRoot));
            });
        } catch(e) {}
        return found;
    }

    function _fxCurve(drive) {
        var n = 1024, curve = new Float32Array(n);
        var k = drive < 0.01 ? 0 : 1 + drive * 29;
        for (var i = 0; i < n; i++) {
            var x = (i / (n - 1)) * 2 - 1;
            curve[i] = k > 0 ? Math.tanh(k * x) / Math.tanh(k) : x;
        }
        return curve;
    }

    function _fxApply() {
        if (!_fxN) return;
        var p = _fxP, n = _fxN;
        // Distortion
        n.dist.curve = _fxCurve(p.distDrive);
        // Ring mod: gain = 1 + depth * sin(freq*t)
        n.ringOsc.frequency.value = p.ringFreq;
        n.ringOscAmp.gain.value   = p.ringDepth;   // oscillator amplitude = depth
        // Delay
        n.delay.delayTime.value = p.delayTime;
        n.delayFb.gain.value    = p.delayFb;
        n.delayDry.gain.value   = 1 - p.delayMix;
        n.delayWet.gain.value   = p.delayMix;
        // Phaser
        n.phaseLFO.frequency.value    = p.phaseRate;
        n.phaseLFOGain.gain.value     = 500 * p.phaseDepth;
        n.phaseDry.gain.value         = 1 - p.phaseDepth * 0.5;
        n.phaseWet.gain.value         = p.phaseDepth * 0.5;
    }

    function _fxSetup(audioEl) {
        // Idempotent: createMediaElementSource() can only be called ONCE per
        // HTMLMediaElement for its lifetime — closing the AudioContext does
        // NOT release that binding. So we wire the chain exactly once and
        // reuse it forever; new files come in via audioEl.src updates only.
        if (_fxCtx) return;

        _fxCtx = new (window.AudioContext || window.webkitAudioContext)();

        try {
            _fxSrc = _fxCtx.createMediaElementSource(audioEl);
        } catch(e) {
            _dbg('FX: createMediaElementSource failed: ' + e);
            _fxCtx = null;   // allow a retry on the next poll if it failed
            return;
        }

        // ── Distortion (WaveShaper) ──────────────────────────────────────
        var dist = _fxCtx.createWaveShaper();
        dist.curve = _fxCurve(0);
        dist.oversample = '2x';

        // ── Ring Mod (oscillator → gain.gain) ───────────────────────────
        // gain = 1.0 base + (osc output × depth) — matches Python: 1 + depth*sin(t)
        var ringGain = _fxCtx.createGain();
        ringGain.gain.value = 1.0;            // base (passthrough when depth=0)
        var ringOsc = _fxCtx.createOscillator();
        ringOsc.type = 'sine';
        ringOsc.frequency.value = _fxP.ringFreq;
        var ringOscAmp = _fxCtx.createGain();
        ringOscAmp.gain.value = 0;            // 0 = no ring mod
        ringOsc.connect(ringOscAmp);
        ringOscAmp.connect(ringGain.gain);    // adds to gain.value
        ringOsc.start();

        // ── Delay (DelayNode + feedback loop) ───────────────────────────
        var delay   = _fxCtx.createDelay(2.0);
        var delayFb = _fxCtx.createGain();
        var delayDry = _fxCtx.createGain();
        var delayWet = _fxCtx.createGain();
        var delayOut = _fxCtx.createGain();   // merge dry + wet
        delay.delayTime.value = _fxP.delayTime;
        delayFb.gain.value    = _fxP.delayFb;
        delayDry.gain.value   = 1;
        delayWet.gain.value   = 0;
        delay.connect(delayFb);
        delayFb.connect(delay);               // feedback loop
        delay.connect(delayWet);
        delayDry.connect(delayOut);
        delayWet.connect(delayOut);

        // ── Phaser (4 allpass BiquadFilters + LFO) ──────────────────────
        var phaseAP = [];
        for (var i = 0; i < 4; i++) {
            var ap = _fxCtx.createBiquadFilter();
            ap.type = 'allpass';
            ap.frequency.value = 200 * Math.pow(4, i / 3.0);
            ap.Q.value = 0.5;
            phaseAP.push(ap);
        }
        var phaseLFO     = _fxCtx.createOscillator();
        var phaseLFOGain = _fxCtx.createGain();
        phaseLFO.frequency.value  = _fxP.phaseRate;
        phaseLFOGain.gain.value   = 0;
        phaseLFO.connect(phaseLFOGain);
        phaseAP.forEach(function(ap) { phaseLFOGain.connect(ap.frequency); });
        phaseLFO.start();
        for (var j = 1; j < phaseAP.length; j++) {
            phaseAP[j - 1].connect(phaseAP[j]);
        }
        var phaseDry = _fxCtx.createGain();
        var phaseWet = _fxCtx.createGain();
        phaseDry.gain.value = 1;
        phaseWet.gain.value = 0;

        // ── Connect the full chain ───────────────────────────────────────
        _fxSrc.connect(dist);
        dist.connect(ringGain);

        ringGain.connect(delayDry);
        ringGain.connect(delay);

        delayOut.connect(phaseDry);
        delayOut.connect(phaseAP[0]);

        phaseAP[phaseAP.length - 1].connect(phaseWet);
        phaseDry.connect(_fxCtx.destination);
        phaseWet.connect(_fxCtx.destination);

        _fxN = {
            dist: dist,
            ringGain: ringGain, ringOsc: ringOsc, ringOscAmp: ringOscAmp,
            delay: delay, delayFb: delayFb, delayDry: delayDry,
            delayWet: delayWet, delayOut: delayOut,
            phaseAP: phaseAP, phaseLFO: phaseLFO, phaseLFOGain: phaseLFOGain,
            phaseDry: phaseDry, phaseWet: phaseWet
        };
        _fxApply();

        // Browsers create AudioContext suspended until a real user gesture.
        // Hook the element's 'play' event (which IS a user gesture) so the
        // context resumes the moment the user hits the play button.
        audioEl.addEventListener('play', function() {
            if (_fxCtx && _fxCtx.state === 'suspended') {
                _fxCtx.resume().catch(function(e) {
                    _dbg('FX: resume() rejected: ' + e);
                });
            }
        });
        // Best-effort early resume (works if user already interacted).
        if (_fxCtx.state === 'suspended') _fxCtx.resume();

        // Tap an AnalyserNode off the dry phase output so audio-reactive
        // viz (VU meter for hardware skin, halo pulse for acid skin) can
        // sample the same signal the user hears.
        try {
            var an = _fxCtx.createAnalyser();
            an.fftSize = 256;
            an.smoothingTimeConstant = 0.7;
            phaseDry.connect(an);
            _fxN.analyser = an;
            _fxN.analyserBuf = new Uint8Array(an.frequencyBinCount);
        } catch(e) {
            _dbg('FX: analyser tap failed: ' + e);
        }

        _dbg('FX chain ready, sr=' + _fxCtx.sampleRate);
    }

    // ── Audio-reactive viz loop (VU meter + acid halo) ──────────────────
    // One rAF loop drives both the hardware-skin VU meter and the
    // acid-skin halo around the slurmify button. The loop is always
    // running but cheaply skips work when no analyser is attached or
    // the corresponding skin is inactive (CSS keeps elements hidden).
    (function _slurmVizLoop() {
        function _rms(buf) {
            var sum = 0;
            for (var i = 0; i < buf.length; i++) {
                var v = (buf[i] - 128) / 128;
                sum += v * v;
            }
            return Math.sqrt(sum / buf.length);
        }
        function _bandAvg(buf, lo, hi) {
            var s = 0, n = Math.max(1, hi - lo);
            for (var i = lo; i < hi; i++) s += buf[i];
            return s / (n * 255);
        }

        var vu = document.getElementById('slurm-vu-meter');
        var halo = document.getElementById('slurm-go-halo');
        var skin;
        var phase = 0;

        function step() {
            phase++;
            skin = document.body && document.body.dataset
                   ? document.body.dataset.skin : 'default';
            var an = _fxN && _fxN.analyser;

            if (an && skin === 'hardware' && vu) {
                an.getByteFrequencyData(_fxN.analyserBuf);
                var ctx = vu.getContext('2d');
                var w = vu.width, h = vu.height;
                ctx.clearRect(0, 0, w, h);
                // 24 vertical bars, log-ish bin spacing.
                var bins = _fxN.analyserBuf;
                var nBars = 32;
                var barW = w / nBars;
                for (var b = 0; b < nBars; b++) {
                    var i = Math.floor(Math.pow(b / nBars, 1.6) * bins.length);
                    var v = bins[i] / 255;
                    var bh = Math.max(1, v * (h - 4));
                    // Amber LED gradient — green low, amber mid, red top
                    var grad = ctx.createLinearGradient(0, h, 0, 0);
                    grad.addColorStop(0,    '#7fff5a');
                    grad.addColorStop(0.55, '#ffb74d');
                    grad.addColorStop(0.85, '#ff5050');
                    ctx.fillStyle = grad;
                    ctx.fillRect(b * barW + 1, h - bh - 2, barW - 2, bh);
                }
            }

            if (an && skin === 'acid' && halo) {
                an.getByteTimeDomainData(_fxN.analyserBuf);
                // Energy in the lower 1/4 of bins ≈ bass band.
                var bass = _bandAvg(_fxN.analyserBuf, 0, 16);
                an.getByteFrequencyData(_fxN.analyserBuf);
                var lo = _bandAvg(_fxN.analyserBuf, 0, 8);
                // Find the slurmify button (closest primary in the same row)
                var btn = document.querySelector('button.primary, button[variant="primary"]');
                if (btn) {
                    var glow = 18 + lo * 80;
                    var spread = 4 + lo * 18;
                    btn.style.boxShadow =
                        '0 0 ' + glow + 'px ' + spread + 'px rgba(255,80,220,0.55), ' +
                        '0 0 ' + (glow * 2) + 'px ' + (spread * 2) +
                        'px rgba(60,200,255,0.35)';
                }
            } else if (skin !== 'acid') {
                // Clear inline glow when leaving acid so other skins aren't tinted.
                var btn2 = document.querySelector('button.primary, button[variant="primary"]');
                if (btn2 && btn2.style.boxShadow) btn2.style.boxShadow = '';
            }

            requestAnimationFrame(step);
        }
        // Defer first frame so the DOM has settled.
        setTimeout(function () { requestAnimationFrame(step); }, 800);
    })();

    // ── Preview-element strategy ────────────────────────────────────────
    // Gradio's gr.Audio wraps its <audio> in WaveSurfer with custom transport
    // controls; createMediaElementSource can only be called once per element
    // ever, so we use a dedicated <audio id="slurm-fx-audio"> in the FX panel.
    //
    // Two parallel mechanisms keep its src in sync with the slurm output:
    //   1. audio_out.change(js=...)  — Gradio fires when the value changes
    //      (Python side, below).
    //   2. The polling loop here     — walks the DOM for any <audio> inside
    //      Gradio's component and mirrors its src into our preview element.
    //      Required because gr.Audio's `change` event timing is unreliable
    //      (it can race with WaveSurfer's lazy mount).
    //
    // The FX chain binds on the preview element's FIRST 'play' event — a
    // real user gesture, so the AudioContext can resume immediately. Only
    // ever bound once for the page's lifetime.

    function _fxSrcUrl(audioEl) {
        // Try every place WaveSurfer/Gradio might stash the URL.
        return (audioEl && (
            audioEl.src ||
            audioEl.currentSrc ||
            audioEl.getAttribute('src') ||
            (audioEl.querySelector && audioEl.querySelector('source') &&
             audioEl.querySelector('source').src) ||
            ''
        )) || '';
    }

    var _fxLastSrc = '';
    var _fxFirstFound = false;
    setInterval(function() {
        var fxAudio = document.getElementById('slurm-fx-audio');
        if (!fxAudio) return;

        var outEl = document.getElementById('slurm-audio-out');
        if (!outEl) return;

        // Walk the (possibly nested) shadow DOM for an <audio> element with
        // a populated src — that's the file Gradio is currently serving.
        var audios = _fxWalk(outEl);
        var srcUrl = '';
        for (var i = 0; i < audios.length; i++) {
            var u = _fxSrcUrl(audios[i]);
            if (u) { srcUrl = u; break; }
        }

        if (!srcUrl) return;

        if (!_fxFirstFound) {
            _fxFirstFound = true;
            _dbg('FX: first audio src observed: ' + srcUrl);
        }

        if (srcUrl !== _fxLastSrc) {
            _fxLastSrc = srcUrl;
            _dbg('FX: mirroring src into preview element: ' + srcUrl);
            try {
                fxAudio.src = srcUrl;
                fxAudio.load();
            } catch(e) {
                _dbg('FX: setting fxAudio.src failed: ' + e);
            }
        }
    }, 400);

    // One-shot: bind the FX chain on the preview element's first play.
    // (A real user gesture — needed for AudioContext to resume.)
    var _fxBindPoll = setInterval(function() {
        var el = document.getElementById('slurm-fx-audio');
        if (!el) return;
        clearInterval(_fxBindPoll);
        el.addEventListener('play', function _onFirstPlay() {
            if (_fxCtx) return;
            _dbg('FX: first play on preview element — binding chain');
            _fxSetup(el);
        });
        _dbg('FX: preview element mounted, will bind chain on first play');
    }, 200);

    // Expose API for Gradio slider js= callbacks
    window.slurmFx = {
        setDist:       function(v) { _fxP.distDrive  = +v; _fxApply(); },
        setRingFreq:   function(v) { _fxP.ringFreq   = +v; _fxApply(); },
        setRingDepth:  function(v) { _fxP.ringDepth  = +v; _fxApply(); },
        setDelayTime:  function(v) { _fxP.delayTime  = +v; _fxApply(); },
        setDelayFb:    function(v) { _fxP.delayFb    = +v; _fxApply(); },
        setDelayMix:   function(v) { _fxP.delayMix   = +v; _fxApply(); },
        setPhaseRate:  function(v) { _fxP.phaseRate  = +v; _fxApply(); },
        setPhaseDepth: function(v) { _fxP.phaseDepth = +v; _fxApply(); },
    };
    _dbg('slurmFx API ready ✓');

    // ── DOM probe after 1 s — dump relevant element state ───────────────
    setTimeout(function() {
        // Try all selector variants to find the button
        var inBtn  = document.querySelector('#slurm-in-btn')
                  || document.querySelector('#slurm-in-btn button')
                  || slurmFindBtn('slurm-in-btn', 'I ] in');
        var outBtn = document.querySelector('#slurm-out-btn')
                  || document.querySelector('#slurm-out-btn button')
                  || slurmFindBtn('slurm-out-btn', 'O ] out');
        var inBox   = document.querySelector('#start-sec-box textarea')
                   || document.querySelector('#start-sec-box input');
        var outBox  = document.querySelector('#end-sec-box textarea')
                   || document.querySelector('#end-sec-box input');
        var audio   = document.querySelector('audio');
        _dbg('--- 1s DOM probe ---');
        _dbg('  #slurm-in-btn  button : ' + (inBtn  ? 'FOUND' : 'MISSING'));
        _dbg('  #slurm-out-btn button : ' + (outBtn ? 'FOUND' : 'MISSING'));
        _dbg('  #start-sec-box input  : ' + (inBox  ? 'FOUND' : 'MISSING'));
        _dbg('  #end-sec-box   input  : ' + (outBox ? 'FOUND' : 'MISSING'));
        _dbg('  audio element         : ' + (audio  ? 'FOUND' : 'MISSING'));
    }, 1000);

    // ── MAX RANDOM hover gif ─────────────────────────────────────────────
    // Tags the radio option whose label text is "MAX RANDOM" with a marker
    // class so CSS can attach a hover-revealed gif. Retried because Gradio
    // renders the Radio after first paint, and re-renders after some events.
    function _slurmTagMaxRandom() {
        var labels = document.querySelectorAll('label');
        var any = false;
        for (var i = 0; i < labels.length; i++) {
            var lbl = labels[i];
            if (lbl.classList.contains('slurm-max-option')) { any = true; continue; }
            // Match by direct text content trimmed — Gradio puts the option
            // text directly inside the <label>, alongside the <input>.
            var t = (lbl.textContent || '').trim();
            if (t === 'MAX RANDOM') {
                lbl.classList.add('slurm-max-option');
                any = true;
                _dbg('MAX RANDOM label tagged');
            }
        }
        return any;
    }
    var _maxTries = 0;
    var _maxIv = setInterval(function () {
        _slurmTagMaxRandom();
        if (++_maxTries > 80) clearInterval(_maxIv);  // ~20s of retries
    }, 250);

    // ── Allow ANY file type on the audio input ────────────────────────────
    // Gradio's gr.Audio renders an <input type="file"> with accept="audio/*"
    // which causes the OS picker to filter out video/media files. We strip
    // the accept attribute so users can upload .mp4/.mov/.mkv etc. The
    // backend (librosa + audioread + ffmpeg) extracts audio transparently.
    function _slurmStripAccept() {
        var inputs = document.querySelectorAll('.slurm-audio input[type="file"]');
        for (var i = 0; i < inputs.length; i++) {
            if (inputs[i].dataset.slurmAcceptStripped) continue;
            inputs[i].removeAttribute('accept');
            inputs[i].dataset.slurmAcceptStripped = '1';
            _dbg('audio input accept= stripped (idx ' + i + ')');
        }
    }
    var _stripTries = 0;
    var _stripIv = setInterval(function () {
        _slurmStripAccept();
        if (++_stripTries > 80) clearInterval(_stripIv);
    }, 250);
})();
"""

CUSTOM_CSS = """
/* ═══════════════════════════════════════════════════════════════════════
   SIENA SLURMER — dark theme
   ═══════════════════════════════════════════════════════════════════════ */
:root {
    --slurm-bg:       #0e0c0c;
    --slurm-cyan:     #00b9e1;
    --slurm-orange:   #ffa600;
    --slurm-rose:     #a09090;
    --slurm-surface:  #161314;
    --slurm-surface2: #1e1a1b;
    --slurm-border:   #2a2323;
    --slurm-border-2: #342c2c;

    /* ── Gradio theme token overrides ─────────────────────────────────── */
    --body-text-color:                    #cdc6c6 !important;
    --body-text-color-subdued:            #7a7070 !important;
    --block-label-text-color:             #9a9090 !important;
    --block-info-text-color:              #6a6060 !important;
    --checkbox-label-text-color:          #cdc6c6 !important;
    --checkbox-label-text-color-selected: #cdc6c6 !important;
    --input-text-fill:                    #cdc6c6 !important;
    --slider-color:                       #00b9e1 !important;
    --background-fill-primary:            #161314 !important;
    --background-fill-secondary:          #0e0c0c !important;
    --border-color-primary:               #2a2323 !important;
    --border-color-accent:                #00b9e1 !important;
    --block-shadow:                       none !important;
    --block-border-width:                 1px !important;
    --block-radius:                       8px !important;
    --input-radius:                       6px !important;
    --container-radius:                   8px !important;
    --spacing-sm:                         6px !important;
    --spacing-md:                         10px !important;
    --spacing-lg:                         16px !important;
    --section-header-text-size:           0.72rem !important;
    --section-header-text-weight:         600 !important;
}

/* ── Page shell ────────────────────────────────────────────────────────── */
.gradio-container {
    background: #0e0c0c !important;
    font-family: "JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace !important;
    max-width: 1100px !important;
    padding: 20px 24px 40px !important;
}
footer { display: none !important; }

/* ── Header ────────────────────────────────────────────────────────────── */
.slurm-header {
    display: flex;
    align-items: center;
    gap: 18px;
    margin-bottom: 0.2rem;
}
.slurm-icon {
    width: 56px;
    height: 56px;
    border-radius: 12px;
    flex-shrink: 0;
    opacity: 0.92;
}
/* Header link wrappers — both the cat icon and the SIENA SLURMER title
   wrap into <a href="https://www.subvoyant.com" target="_blank">. Strip
   default anchor styling (no underline, inherit color/gradient) but keep
   cursor: pointer + subtle hover brightness so it's clearly clickable. */
.slurm-header-link,
.slurm-header-link:visited,
.slurm-header-link:active,
h1.slurm-title .slurm-header-link {
    text-decoration: none !important;
    color: inherit !important;
    background: none !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    -webkit-text-fill-color: inherit !important;
    cursor: pointer;
    display: inline-block;
    transition: opacity 0.15s ease, filter 0.15s ease;
}
/* Keep the title's gradient text trick when the title is wrapped in <a> */
h1.slurm-title .slurm-header-link {
    background: linear-gradient(90deg, #00b9e1 0%, #ffa600 100%) !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
}
.slurm-header-link:hover { opacity: 1; filter: brightness(1.15); }
.slurm-header-link:hover .slurm-icon { opacity: 1; }
.slurm-header-text { display: flex; flex-direction: column; }
h1.slurm-title {
    font-size: 2.6rem;
    font-weight: 800;
    letter-spacing: -0.03em;
    background: linear-gradient(90deg, #00b9e1 0%, #ffa600 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.1em 0;
    line-height: 1;
}
.slurm-tag {
    color: #4e4646;
    font-size: 0.7rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 0;
}
/* subtitle markdown */
.gradio-container > .main > .wrap > .gap > p,
.gradio-container p {
    color: #5a5252 !important;
    font-size: 0.78rem !important;
    margin: 0 0 1rem 0 !important;
}
.gradio-container p strong { color: #7a7070 !important; font-weight: 600 !important; }

/* ── Blocks / panels ───────────────────────────────────────────────────── */
.gradio-container .block,
.gradio-container .gr-block,
.gradio-container fieldset {
    background: #161314 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 8px !important;
    box-shadow: none !important;
    padding: 10px 12px !important;
}
/* tighten gap between stacked form controls */
.gradio-container .gap,
.gradio-container .form {
    gap: 8px !important;
}

/* ── Audio player ──────────────────────────────────────────────────────── */
/* Make waveform container dark and fix the scrollbar/timestamp overlap */
.gradio-container .waveform-container,
.gradio-container [class*="waveform"] {
    background: #0e0c0c !important;
    border-radius: 6px !important;
}
/* Fix scrollbar sitting on top of timestamps:
   hide the horizontal scrollbar inside the waveform scroll area */
.gradio-container .waveform-container > div,
.gradio-container [class*="waveform"] > div {
    scrollbar-width: none !important;        /* Firefox */
    -ms-overflow-style: none !important;     /* IE/Edge */
}
.gradio-container .waveform-container > div::-webkit-scrollbar,
.gradio-container [class*="waveform"] > div::-webkit-scrollbar {
    display: none !important;
}
/* Timestamp row — lift above any overflow */
.gradio-container .timestamps,
.gradio-container [class*="timestamps"] {
    position: relative !important;
    z-index: 2 !important;
    color: #4e4646 !important;
    font-size: 0.7rem !important;
    padding: 2px 0 0 0 !important;
}
/* Audio block label */
.gradio-container .block > .label-wrap span {
    font-size: 0.7rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #4e4646 !important;
}

/* ── Sliders ───────────────────────────────────────────────────────────── */
.gradio-container input[type="range"] {
    accent-color: #00b9e1;
    height: 3px !important;
}
/* Label + info for sliders/checkboxes */
.gradio-container .label-wrap > span { font-size: 0.75rem !important; }
.gradio-container .info,
.gradio-container [class*="info"] { font-size: 0.67rem !important; color: #4e4646 !important; }

/* ── Text inputs / dropdowns ───────────────────────────────────────────── */
.gradio-container input[type="number"],
.gradio-container input[type="text"],
.gradio-container textarea,
.gradio-container select {
    background: #0e0c0c !important;
    color: #cdc6c6 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    font-size: 0.8rem !important;
    padding: 4px 8px !important;
}
.gradio-container select option {
    background: #161314 !important;
    color: #cdc6c6 !important;
}

/* ── In/Out bar ────────────────────────────────────────────────────────── */
#slurm-inout-bar {
    background: #0f0d0d !important;
    border: 1px solid #2a2323 !important;
    border-radius: 6px !important;
    padding: 4px 8px !important;
    margin: 4px 0 !important;
    display: flex !important;
    flex-wrap: nowrap !important;
    gap: 5px !important;
    align-items: center !important;
}
#slurm-inout-bar > div { flex-shrink: 0; }
#slurm-clock-wrap {
    color: #00b9e1;
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.88rem;
    letter-spacing: 0.05em;
    min-width: 84px;
    padding: 0 2px;
}
.slurm-io-btn,
.slurm-io-btn > .wrap,
.slurm-io-btn button {
    background: transparent !important;
    color: #5a5252 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    font-family: "JetBrains Mono", ui-monospace, monospace !important;
    font-size: 0.72rem !important;
    padding: 1px 8px !important;
    min-width: unset !important;
    min-height: unset !important;
    height: auto !important;
    line-height: 1.7 !important;
    transition: color 0.15s, border-color 0.15s !important;
}
.slurm-io-btn button:hover {
    background: transparent !important;
    color: #cdc6c6 !important;
    border-color: #00b9e1 !important;
}
.slurm-io-clear button { color: #4a4040 !important; }
.slurm-io-clear button:hover {
    color: #ffa600 !important;
    border-color: #ffa600 !important;
}

/* ── Compact text inputs — unified typography ─────────────────────────── */
/* The in/out sec boxes and the seed textbox all share the same compact
   single-line look, matching the base font-size (0.8rem) so they're
   typographically consistent with every other text input in the app.
   Gradio renders Textbox labels TWO ways depending on whether info= is
   set: bare <label> when info is absent (browser default size, large),
   vs <div class="label-wrap"><span> when info is present (smaller).
   We force both patterns to look identical so labels stay consistent
   regardless of whether the component has an info subtitle. */
#start-sec-box, #end-sec-box, #slurm-seed-box {
    min-height: unset !important;
}
#start-sec-box input, #end-sec-box input,
#start-sec-box textarea, #end-sec-box textarea,
#slurm-seed-box input, #slurm-seed-box textarea {
    font-size: 0.8rem !important;
    padding: 3px 8px !important;
    line-height: 1.5 !important;
    min-height: unset !important;
    height: auto !important;
}
/* Force label-rendering consistency across BOTH info-present and info-absent
   Textbox patterns. Catch every label/wrap variant Gradio might render. */
#start-sec-box label, #start-sec-box .label-wrap > span,
#start-sec-box .label-wrap span,
#end-sec-box label, #end-sec-box .label-wrap > span,
#end-sec-box .label-wrap span,
#slurm-seed-box label, #slurm-seed-box .label-wrap > span,
#slurm-seed-box .label-wrap span {
    font-size: 0.75rem !important;
    font-weight: 400 !important;
    color: #9a9090 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    line-height: 1.4 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Pin in/out input boxes to a consistent baseline. Even with matching info=
   on both, Gradio's internal label-wrap padding can differ by a few pixels,
   pushing the input boxes to slightly different y-positions. Forcing the
   container to flex-column with content aligned at the BOTTOM ensures the
   inputs land on the same baseline regardless of what's above them. */
#start-sec-box, #end-sec-box {
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-end !important;
    min-height: 78px !important;
}
#start-sec-box > *, #end-sec-box > * {
    flex-shrink: 0 !important;
}
/* Also tighten the info subtitle vertical rhythm for both, so neither
   adds extra space between info and input. */
#start-sec-box .info, #end-sec-box .info,
#start-sec-box [class*="info"], #end-sec-box [class*="info"] {
    margin: 0 !important;
    padding: 0 !important;
    line-height: 1.3 !important;
}

/* ── Neutralize Gradio's :focus-within block highlight ────────────────── */
/* By default, Gradio recolors a block's border AND label to the accent
   color (cyan, in our theme) when any input inside it has focus. Result:
   "in (sec)" looks dramatically different from "out (sec)" depending on
   which one was last clicked — not a setting on the component, just
   default focus-within behavior. We keep the block visually identical
   regardless of focus; the input itself still shows a cursor so users
   know where they're typing. */
.gradio-container .block:focus-within,
.gradio-container .gr-block:focus-within,
.gradio-container fieldset:focus-within,
#start-sec-box:focus-within,
#end-sec-box:focus-within,
#slurm-seed-box:focus-within {
    border-color: #2a2323 !important;
    background: #161314 !important;
    box-shadow: none !important;
}
.gradio-container .block:focus-within .label-wrap > span,
.gradio-container .block:focus-within > .label-wrap span,
.gradio-container .block:focus-within label,
#start-sec-box:focus-within .label-wrap > span,
#end-sec-box:focus-within .label-wrap > span,
#slurm-seed-box:focus-within .label-wrap > span {
    color: #9a9090 !important;  /* same as --block-label-text-color */
}
/* Keep input focus subtle but visible (1px brighter inner border) */
#start-sec-box input:focus, #end-sec-box input:focus,
#slurm-seed-box input:focus, #start-sec-box textarea:focus,
#end-sec-box textarea:focus, #slurm-seed-box textarea:focus {
    outline: none !important;
    border-color: #3a3333 !important;
}

/* ── Primary (slurmify) button ─────────────────────────────────────────── */
.gradio-container button.primary,
.gradio-container button[variant="primary"] {
    background: #00b9e1 !important;
    color: #0a0808 !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    font-size: 0.9rem !important;
    transition: filter 0.15s !important;
}
.gradio-container button.primary:hover,
.gradio-container button[variant="primary"]:hover {
    filter: brightness(1.12) !important;
}
/* quit button */
.gradio-container button.stop,
.gradio-container button[variant="stop"] {
    background: transparent !important;
    border: 1px solid #2a2323 !important;
    color: #5a5252 !important;
    font-size: 0.72rem !important;
    border-radius: 6px !important;
}
.gradio-container button.stop:hover,
.gradio-container button[variant="stop"]:hover {
    border-color: #6a3030 !important;
    color: #b06060 !important;
}

/* ── FX accordion panel ────────────────────────────────────────────────── */
#slurm-fx-panel > .label-wrap span,
#slurm-fx-panel > .block-label span {
    color: #00b9e1 !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
}
#slurm-fx-panel .block {
    background: #0f0d0d !important;
    border: 1px solid #231f1f !important;
}
/* FX section headings inside accordion */
.slurm-fx-section {
    color: #4e4646;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding: 2px 0 4px 0;
    border-bottom: 1px solid #231f1f;
    margin-bottom: 2px;
}
/* Burn button */
#slurm-burn-btn button {
    background: linear-gradient(90deg, #00b9e1 0%, #0099c8 100%) !important;
    color: #080707 !important;
    border: none !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em !important;
    font-size: 0.82rem !important;
    border-radius: 6px !important;
}
#slurm-burn-btn button:hover {
    filter: brightness(1.15) !important;
}

/* ── Dancer / loading gif ──────────────────────────────────────────────── */
#siena-dancer {
    display: flex;
    justify-content: center;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
#siena-dancer img { max-width: 180px; }

/* ═══════════════════════════════════════════════════════════════════════
   Skin picker (visible in all skins, restyled per-skin below)
   ═══════════════════════════════════════════════════════════════════════ */
.slurm-skin-wrap {
    margin-left: auto;
    display: flex; align-items: center; gap: 6px;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #6a6060;
}
.slurm-skin-wrap select {
    background: #161314; color: #cdc6c6;
    border: 1px solid #2a2323; border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.7rem;
    font-family: inherit;
}

/* ═══════════════════════════════════════════════════════════════════════
   Audio-reactive elements — hidden by default, made visible per-skin.
   ═══════════════════════════════════════════════════════════════════════ */
#slurm-vu-meter, #slurm-go-halo {
    display: none;
}

/* ═══════════════════════════════════════════════════════════════════════
   Compact controls — default-skin only.
   The browser-default slider thumb is ~16-20 px and feels oversized
   against our slim 3 px tracks; we explicitly draw it at 12 px and
   tighten the block / gap / padding rhythm. Type sizes are untouched
   because the labels and value readouts are already at a good size.
   The Acid and Hardware skins reach into the slider machinery with
   higher-specificity selectors and override these intentionally.
   ═══════════════════════════════════════════════════════════════════════ */
:root[data-skin="default"] .gradio-container .block,
:root[data-skin="default"] .gradio-container .gr-block,
:root[data-skin="default"] .gradio-container fieldset,
body[data-skin="default"] .gradio-container .block,
body[data-skin="default"] .gradio-container .gr-block,
body[data-skin="default"] .gradio-container fieldset {
    padding: 6px 10px !important;       /* was 10px 12px */
}
body[data-skin="default"] .gradio-container .gap,
body[data-skin="default"] .gradio-container .form {
    gap: 5px !important;                /* was 8px */
}
body[data-skin="default"] .gradio-container .block > .label-wrap {
    margin-bottom: 1px !important;
}
body[data-skin="default"] .gradio-container .info,
body[data-skin="default"] .gradio-container [class*="info"] {
    margin-top: 0 !important;
    line-height: 1.2 !important;
}

/* Smaller, explicitly-styled slider thumbs (default skin) */
body[data-skin="default"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #00b9e1;
    border: 2px solid #0e0c0c;
    box-shadow: 0 0 0 1px #2a2323;
    margin-top: -4.5px;       /* (12px thumb - 3px track) / 2, fudged to center */
    cursor: grab;
}
body[data-skin="default"] .gradio-container input[type="range"]::-moz-range-thumb {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #00b9e1;
    border: 2px solid #0e0c0c;
    box-shadow: 0 0 0 1px #2a2323;
    cursor: grab;
}

/* Tighter inputs / dropdowns / numeric boxes (default skin) */
body[data-skin="default"] .gradio-container input[type="number"],
body[data-skin="default"] .gradio-container input[type="text"],
body[data-skin="default"] .gradio-container textarea,
body[data-skin="default"] .gradio-container select {
    padding: 3px 7px !important;       /* was 4px 8px */
    min-height: unset !important;
}

/* Tighter buttons (default skin) — but the primary slurmify button stays
   visually substantial because it's the action target. */
body[data-skin="default"] .gradio-container button {
    padding: 5px 12px !important;
    min-height: unset !important;
}
body[data-skin="default"] .gradio-container button.primary,
body[data-skin="default"] .gradio-container button[variant="primary"] {
    padding: 9px 16px !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   SKIN: ACID CATHEDRAL  (body[data-skin="acid"])
   Trippy / liquid / audio-reactive. Glassmorphic accordions, animated
   rainbow title, slow hue-rotation on background, glowing slider thumbs.
   ═══════════════════════════════════════════════════════════════════════ */
@keyframes slurm-acid-drift {
    0%   { background-position:   0% 50%, 100% 50%, 50% 0%;   filter: hue-rotate(0deg);   }
    50%  { background-position: 100% 50%,   0% 50%, 50% 100%; filter: hue-rotate(180deg); }
    100% { background-position:   0% 50%, 100% 50%, 50% 0%;   filter: hue-rotate(360deg); }
}
@keyframes slurm-acid-text {
    0%   { background-position:   0% 50%; }
    100% { background-position: 200% 50%; }
}
@keyframes slurm-acid-pulse {
    0%, 100% { box-shadow: 0 0 30px 6px rgba(180, 60, 230, 0.55),
                           0 0 80px 20px rgba(60, 200, 255, 0.35); }
    50%      { box-shadow: 0 0 60px 14px rgba(255, 80, 220, 0.7),
                           0 0 140px 32px rgba(120, 220, 255, 0.5); }
}

body[data-skin="acid"] .gradio-container {
    background:
        radial-gradient(ellipse at 20% 30%, #ff3eb1 0%, transparent 55%),
        radial-gradient(ellipse at 80% 60%, #2bd4ff 0%, transparent 55%),
        radial-gradient(ellipse at 50% 90%, #b07cff 0%, transparent 60%),
        #1a0824 !important;
    background-size: 200% 200%, 200% 200%, 200% 200%, 100% 100%;
    animation: slurm-acid-drift 28s linear infinite;
    color: #fff !important;
}
body[data-skin="acid"] {
    background: #1a0824 !important;
}

/* Title — chunky display font with animated rainbow background-clip */
body[data-skin="acid"] .slurm-title {
    font-family: 'Bagel Fat One', 'Inter', system-ui, sans-serif !important;
    font-size: 3.4rem !important;
    font-weight: 400 !important;
    letter-spacing: -0.02em !important;
    background: linear-gradient(90deg,
        #ff3eb1, #ffea00, #2bd4ff, #b07cff, #ff3eb1) !important;
    background-size: 200% auto !important;
    -webkit-background-clip: text !important;
            background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    color: transparent !important;
    animation: slurm-acid-text 6s linear infinite;
    text-shadow: 0 2px 30px rgba(255, 60, 180, 0.4) !important;
}
body[data-skin="acid"] .slurm-tag {
    color: rgba(255, 255, 255, 0.7) !important;
    letter-spacing: 0.18em !important;
}
body[data-skin="acid"] .slurm-icon {
    filter: drop-shadow(0 0 12px rgba(255, 200, 255, 0.6))
            drop-shadow(0 0 4px rgba(180, 100, 255, 0.9)) !important;
}

/* Glassmorphic accordions and blocks */
body[data-skin="acid"] .gradio-container .block,
body[data-skin="acid"] .gradio-container fieldset,
body[data-skin="acid"] #slurm-fx-panel,
body[data-skin="acid"] #slurm-video-panel {
    background: rgba(25, 10, 40, 0.35) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
    backdrop-filter: blur(18px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(18px) saturate(180%) !important;
    border-radius: 14px !important;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.4),
                inset 0 0 1px rgba(255, 255, 255, 0.4) !important;
}
body[data-skin="acid"] .gradio-container .label-wrap span,
body[data-skin="acid"] .gradio-container .block > label,
body[data-skin="acid"] .gradio-container input,
body[data-skin="acid"] .gradio-container textarea,
body[data-skin="acid"] .gradio-container select {
    color: #fff !important;
}
body[data-skin="acid"] .gradio-container .info,
body[data-skin="acid"] .gradio-container [class*="info"] {
    color: rgba(255, 255, 255, 0.55) !important;
}
body[data-skin="acid"] .gradio-container input[type="text"],
body[data-skin="acid"] .gradio-container input[type="number"],
body[data-skin="acid"] .gradio-container textarea {
    background: rgba(0, 0, 0, 0.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
}

/* Sliders — glowing thumbs, gradient tracks (smaller than v1) */
body[data-skin="acid"] .gradio-container input[type="range"]::-webkit-slider-runnable-track {
    background: linear-gradient(90deg, #ff3eb1, #2bd4ff, #b07cff) !important;
    height: 4px !important; border-radius: 2px !important;
}
body[data-skin="acid"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #fff !important;
    border: 2px solid #ff3eb1 !important;
    margin-top: -5px;
    box-shadow: 0 0 10px 2px rgba(255, 100, 220, 0.75),
                0 0 26px 6px rgba(60, 200, 255, 0.35) !important;
    cursor: grab;
}
body[data-skin="acid"] .gradio-container input[type="range"]::-moz-range-thumb {
    width: 14px; height: 14px;
    border-radius: 50%;
    background: #fff !important;
    border: 2px solid #ff3eb1 !important;
    box-shadow: 0 0 10px 2px rgba(255, 100, 220, 0.75),
                0 0 26px 6px rgba(60, 200, 255, 0.35) !important;
    cursor: grab;
}
/* Compact block padding for acid skin too */
body[data-skin="acid"] .gradio-container .block,
body[data-skin="acid"] .gradio-container fieldset {
    padding: 6px 10px !important;
}
body[data-skin="acid"] .gradio-container .gap,
body[data-skin="acid"] .gradio-container .form {
    gap: 5px !important;
}

/* Buttons — primary slurmify gets the full glow treatment */
body[data-skin="acid"] .gradio-container button.primary,
body[data-skin="acid"] .gradio-container button[variant="primary"] {
    background: linear-gradient(90deg, #ff3eb1, #b07cff, #2bd4ff) !important;
    background-size: 200% auto !important;
    color: #fff !important;
    border: 1px solid rgba(255, 255, 255, 0.35) !important;
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5) !important;
    box-shadow: 0 0 24px rgba(255, 100, 220, 0.45) !important;
    animation: slurm-acid-text 4s linear infinite;
}
body[data-skin="acid"] .gradio-container button.primary:hover,
body[data-skin="acid"] .gradio-container button[variant="primary"]:hover {
    box-shadow: 0 0 36px 4px rgba(255, 100, 220, 0.65) !important;
    filter: brightness(1.18) !important;
}

/* The dancer rides above the shader-y background */
body[data-skin="acid"] #siena-dancer img {
    mix-blend-mode: screen !important;
    filter: hue-rotate(0deg) saturate(1.4) !important;
}

/* Halo around the slurmify button — audio-reactive (set by JS) */
body[data-skin="acid"] #slurm-go-halo {
    display: block !important;
    position: relative;
    border-radius: 16px;
    padding: 0;
    margin: 6px 0;
    pointer-events: none;
    height: 0;
}

/* Skin picker on acid */
body[data-skin="acid"] .slurm-skin-wrap { color: rgba(255, 255, 255, 0.7); }
body[data-skin="acid"] .slurm-skin-wrap select {
    background: rgba(0, 0, 0, 0.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.3) !important;
    color: #fff !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   SKIN: HARDWARE RACK  (body[data-skin="hardware"])
   Brushed metal panels, recessed knurled knobs, LCD readouts, big LEDs.
   ═══════════════════════════════════════════════════════════════════════ */
body[data-skin="hardware"] {
    background:
        repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.025) 0px,
            rgba(0,0,0,0)   1px,
            rgba(0,0,0,0.04) 2px,
            rgba(0,0,0,0)   3px),
        linear-gradient(180deg, #2a2826 0%, #1d1c1a 50%, #232120 100%) !important;
    color: #d8d2c0 !important;
}
body[data-skin="hardware"] .gradio-container {
    background: transparent !important;
    color: #d8d2c0 !important;
}

/* Title — vintage rack-mount feel */
body[data-skin="hardware"] .slurm-title {
    font-family: 'Major Mono Display', 'Share Tech Mono', monospace !important;
    font-size: 2.2rem !important;
    color: #f4ecd0 !important;
    letter-spacing: 0.12em !important;
    text-shadow:
        0 1px 0 rgba(255, 255, 255, 0.18),
        0 -1px 0 rgba(0, 0, 0, 0.6),
        0 0 18px rgba(255, 220, 160, 0.15) !important;
}
body[data-skin="hardware"] .slurm-tag {
    font-family: 'Share Tech Mono', monospace !important;
    color: #948c78 !important;
    letter-spacing: 0.15em !important;
    font-size: 0.66rem !important;
}

/* Brushed-metal panels around blocks/accordions */
body[data-skin="hardware"] .gradio-container .block,
body[data-skin="hardware"] .gradio-container fieldset,
body[data-skin="hardware"] #slurm-fx-panel,
body[data-skin="hardware"] #slurm-video-panel {
    background:
        repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.02) 0px,
            rgba(0,0,0,0)   1px,
            rgba(0,0,0,0.06) 2px,
            rgba(0,0,0,0)   3px),
        linear-gradient(180deg, #3a3631 0%, #2a2724 50%, #353027 100%) !important;
    border: 1px solid #1a1614 !important;
    border-radius: 8px !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 235, 200, 0.08),
        inset 0 -1px 0 rgba(0, 0, 0, 0.6),
        0 2px 6px rgba(0, 0, 0, 0.6) !important;
    /* Faux corner screws */
    position: relative;
}
body[data-skin="hardware"] .gradio-container .block::before,
body[data-skin="hardware"] .gradio-container .block::after,
body[data-skin="hardware"] #slurm-fx-panel::before,
body[data-skin="hardware"] #slurm-fx-panel::after {
    content: "";
    position: absolute;
    width: 10px; height: 10px;
    border-radius: 50%;
    background:
        radial-gradient(circle at 35% 35%,
            #d6cfb8 0%, #807866 45%, #1a1612 90%);
    box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.6),
                0 0 1px rgba(0, 0, 0, 0.6);
    pointer-events: none;
    z-index: 2;
}
body[data-skin="hardware"] .gradio-container .block::before { top: 6px; left: 6px; }
body[data-skin="hardware"] .gradio-container .block::after  { top: 6px; right: 6px; }

/* Section headings — engraved label feel */
body[data-skin="hardware"] .slurm-fx-section,
body[data-skin="hardware"] .gradio-container .label-wrap span,
body[data-skin="hardware"] .gradio-container .block > label {
    font-family: 'Major Mono Display', monospace !important;
    color: #f4ecd0 !important;
    text-shadow: 0 1px 0 rgba(0, 0, 0, 0.7),
                 0 -1px 0 rgba(255, 235, 200, 0.06) !important;
    letter-spacing: 0.12em !important;
}
body[data-skin="hardware"] .gradio-container .info,
body[data-skin="hardware"] .gradio-container [class*="info"] {
    font-family: 'Share Tech Mono', monospace !important;
    color: #948c78 !important;
}

/* Recessed slider grooves with knurled chrome thumbs */
body[data-skin="hardware"] .gradio-container input[type="range"] {
    height: 28px;
}
body[data-skin="hardware"] .gradio-container input[type="range"]::-webkit-slider-runnable-track {
    background: linear-gradient(180deg, #100e0c 0%, #1f1c19 50%, #100e0c 100%) !important;
    height: 8px !important;
    border-radius: 4px !important;
    box-shadow:
        inset 0 1px 2px rgba(0, 0, 0, 0.9),
        inset 0 -1px 0 rgba(255, 235, 200, 0.05) !important;
    border: 1px solid #0c0a08 !important;
}
body[data-skin="hardware"] .gradio-container input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 24px; height: 24px;
    margin-top: -9px;
    border-radius: 50%;
    background:
        repeating-conic-gradient(from 0deg,
            #d6cfb8 0deg, #b8b09a 8deg,
            #d6cfb8 16deg, #807866 24deg),
        radial-gradient(circle at 35% 35%, #f4ecd0, #807866) !important;
    border: 1px solid #1a1612 !important;
    box-shadow:
        0 2px 4px rgba(0, 0, 0, 0.7),
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        inset 0 -2px 4px rgba(0, 0, 0, 0.5) !important;
    cursor: grab;
}

/* Numeric readouts — LCD-amber on smoked glass */
body[data-skin="hardware"] .gradio-container input[type="number"],
body[data-skin="hardware"] .gradio-container input[type="text"],
body[data-skin="hardware"] .gradio-container textarea {
    background: #0a0805 !important;
    color: #ffb74d !important;
    font-family: 'VT323', 'Share Tech Mono', monospace !important;
    font-size: 1rem !important;
    border: 1px solid #0c0a08 !important;
    border-radius: 3px !important;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.9),
                inset 0 0 8px rgba(255, 150, 60, 0.08) !important;
    text-shadow: 0 0 6px rgba(255, 150, 60, 0.6) !important;
    letter-spacing: 0.05em !important;
}

/* Buttons — engraved metal */
body[data-skin="hardware"] .gradio-container button.primary,
body[data-skin="hardware"] .gradio-container button[variant="primary"],
body[data-skin="hardware"] #slurm-burn-btn button,
body[data-skin="hardware"] #slurm-video-btn button {
    background: linear-gradient(180deg, #c9c1a8 0%, #a89e83 50%, #877e63 100%) !important;
    color: #1a1612 !important;
    font-family: 'Major Mono Display', monospace !important;
    letter-spacing: 0.1em !important;
    border: 1px solid #1a1612 !important;
    border-radius: 4px !important;
    text-shadow: 0 1px 0 rgba(255, 235, 200, 0.4) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.5),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        0 2px 4px rgba(0, 0, 0, 0.5) !important;
}
body[data-skin="hardware"] .gradio-container button.primary:hover {
    filter: brightness(1.08);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.6),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        0 2px 8px rgba(255, 150, 60, 0.3) !important;
}

/* LED indicator next to the checkboxes — JS sets data-on per state */
body[data-skin="hardware"] input[type="checkbox"] {
    appearance: none; -webkit-appearance: none;
    width: 16px; height: 16px;
    border-radius: 50%;
    background:
        radial-gradient(circle at 35% 35%, #4a1a1a 0%, #2a0a0a 70%, #100404 100%) !important;
    border: 1px solid #1a1612 !important;
    box-shadow:
        inset 0 1px 2px rgba(0, 0, 0, 0.9),
        0 0 0 2px #2a2826 !important;
    cursor: pointer;
    position: relative;
}
body[data-skin="hardware"] input[type="checkbox"]:checked {
    background:
        radial-gradient(circle at 35% 35%, #ff5050 0%, #ff1010 50%, #b00808 100%) !important;
    box-shadow:
        inset 0 1px 2px rgba(255, 200, 200, 0.4),
        0 0 12px 2px rgba(255, 60, 60, 0.7),
        0 0 0 2px #2a2826 !important;
}

/* VU meter visible only here */
body[data-skin="hardware"] #slurm-vu-meter {
    display: block !important;
    width: 100%;
    height: 28px;
    margin: 6px 0 0 0;
    background:
        linear-gradient(180deg, #100e0c 0%, #1f1c19 50%, #100e0c 100%) !important;
    border: 1px solid #0c0a08 !important;
    border-radius: 4px !important;
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.8) !important;
}

/* Skin picker on hardware */
body[data-skin="hardware"] .slurm-skin-wrap {
    color: #948c78;
    font-family: 'Major Mono Display', monospace;
}
body[data-skin="hardware"] .slurm-skin-wrap select {
    background: #0a0805 !important;
    color: #ffb74d !important;
    border: 1px solid #1a1612 !important;
    font-family: 'Share Tech Mono', monospace !important;
}
"""


# ── Max-the-tester gif: hover reveal on MAX RANDOM slice option ───────────
# Tiny (2.5 KB) so base64-inlining is the obvious call — no extra HTTP
# request, no PyInstaller asset path concerns. Mirrors the _ICON_B64 pattern.
_MAX_GIF_B64 = "R0lGODlhUgBvAKIHADwpHdfX1tKrjamGZ+3Jr7O5rmxVRf///yH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDI3LjYgKE1hY2ludG9zaCkiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6NjE2RTM1MDczRkUxMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6NjE2RTM1MDgzRkUxMTFGMUJGNERFNUMxMUQ0RTFFRUMiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDo2MTZFMzUwNTNGRTExMUYxQkY0REU1QzExRDRFMUVFQyIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDo2MTZFMzUwNjNGRTExMUYxQkY0REU1QzExRDRFMUVFQyIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PgH//v38+/r5+Pf29fTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dDPzs3My8rJyMfGxcTD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"

CUSTOM_CSS += f"""
/* MAX RANDOM hover gif — tagged by INIT_JS as .slurm-max-option */
.slurm-max-option {{
    position: relative;
    overflow: visible !important;
}}
.slurm-max-option::after {{
    content: "";
    position: absolute;
    /* MAX RANDOM is the last radio option — right of it is empty space, so
       positioning the gif there avoids any overflow:hidden ancestor clipping. */
    left: calc(100% + 12px);
    bottom: -12px;
    transform: translateX(-12px) scale(0.55);
    transform-origin: left bottom;
    width: 110px;
    height: 149px;
    background-image: url("data:image/gif;base64,{_MAX_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease, transform 0.18s ease;
    z-index: 9999;
    filter: drop-shadow(0 6px 14px rgba(0,0,0,0.55));
}}
.slurm-max-option:hover::after {{
    opacity: 1;
    transform: translateX(0) scale(1);
}}
"""


# ── Bob's gif: hover slide-up reveal on '📁 reveal temp files' button ─
# Bob suggested the reveal-temp-files feature, so he gets the easter egg.
# 99x361 portrait — slides up from below the button on hover, with a
# bouncy spring easing so the reveal feels playful (Bob makes an entrance).
_BOB_GIF_B64 = "R0lGODlhYwBpAaIHAF9UTMCzqQq7NvwFORkZwe2GADw7NgAAACH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDIwMjYgTWFjaW50b3NoIiB4bXBNTTpJbnN0YW5jZUlEPSJ4bXAuaWlkOjU5MUJDRDVDNDAwQTExRjFCRjRERTVDMTFENEUxRUVDIiB4bXBNTTpEb2N1bWVudElEPSJ4bXAuZGlkOjU5MUJDRDVENDAwQTExRjFCRjRERTVDMTFENEUxRUVDIj4gPHhtcE1NOkRlcml2ZWRGcm9tIHN0UmVmOmluc3RhbmNlSUQ9InhtcC5paWQ6NTkxQkNENUE0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHN0UmVmOmRvY3VtZW50SUQ9InhtcC5kaWQ6NTkxQkNENUI0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiLz4gPC9yZGY6RGVzY3JpcHRpb24+IDwvcmRmOlJERj4gPC94OnhtcG1ldGE+IDw/eHBhY2tldCBlbmQ9InIiPz4B//79/Pv6+fj39vX08/Lx8O/u7ezr6uno5+bl5OPi4eDf3t3c29rZ2NfW1dTT0tHQz87NzMvKycjHxsXEw8LB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"

CUSTOM_CSS += f"""
/* Bob hover gif — applied to the reveal-temp-files button via
   elem_classes=["slurm-bob-option"]. Tall portrait sized to
   ~75x274 (preserves the 99:361 aspect ratio of the source). */
.slurm-bob-option {{
    position: relative;
    overflow: visible !important;
}}
.slurm-bob-option::after {{
    content: "";
    position: absolute;
    /* Anchor at the BOTTOM edge of the button so Bob springs UPWARD
       from the button itself. The translateY(20px) start-state hides
       him just below — he then slides up + scales in on hover. */
    bottom: 0;
    left: 50%;
    transform: translateX(-50%) translateY(20px) scale(0.6);
    transform-origin: bottom center;
    width: 75px;
    height: 274px;
    background-image: url("data:image/gif;base64,{_BOB_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: bottom center;
    opacity: 0;
    pointer-events: none;
    /* Bouncy cubic-bezier (overshoot at the end) gives Bob the
       playful spring on his way up — befits an easter egg. */
    transition: opacity 0.18s ease,
                transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 9999;
    filter: drop-shadow(0 6px 16px rgba(0,0,0,0.55));
}}
.slurm-bob-option:hover::after {{
    opacity: 1;
    /* Final pose: anchored at button bottom, sprung fully up. */
    transform: translateX(-50%) translateY(0) scale(1);
}}
"""


# ── Hoberman-Max gif: hover popup on the 🎲 randomize all button ────────
# Different image from .slurm-max-option (which still uses the original
# Max headshot for the MAX RANDOM radio). Source is 371x307 landscape.
_HOBERMAN_GIF_B64 = "R0lGODlhcwEzAaIHAP8AAMRMPQEv3ADAF+ucHdeaYvzMJwAAACH/C1hNUCBEYXRhWE1QPD94cGFja2V0IGJlZ2luPSLvu78iIGlkPSJXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQiPz4gPHg6eG1wbWV0YSB4bWxuczp4PSJhZG9iZTpuczptZXRhLyIgeDp4bXB0az0iQWRvYmUgWE1QIENvcmUgMTAuMC1jMDAwIDc5LmQyMGU0NjYzMCwgMjAyNS8xMi8wOS0wMjoxMToyMyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wTU09Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9tbS8iIHhtbG5zOnN0UmVmPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvc1R5cGUvUmVzb3VyY2VSZWYjIiB4bWxuczp4bXA9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC8iIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6NTkxQkNENjE0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6NTkxQkNENjA0MDBBMTFGMUJGNERFNUMxMUQ0RTFFRUMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIDIwMjYgTWFjaW50b3NoIj4gPHhtcE1NOkRlcml2ZWRGcm9tIHN0UmVmOmluc3RhbmNlSUQ9IjI3RDA5OTdFMjg1QTU1NkJGOEM0ODJFQzlCMkQxM0RBIiBzdFJlZjpkb2N1bWVudElEPSIyN0QwOTk3RTI4NUE1NTZCRjhDNDgyRUM5QjJEMTNEQSIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PgH//v38+/r5+Pf29fTz8vHw7+7t7Ovq6ejn5uXk4+Lh4N/e3dzb2tnY19bV1NPS0dDPzs3My8rJyMfGxcTDwsHAv769vLu6ubi3trW0s7Kx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"

# ── Max as a slide-up popup (matches Bob's animation pattern) ────────
# When the randomize all button gets a hover popup, use Bob's bottom-up
# spring-rise animation for visual consistency between the two utility
# buttons. The MAX RANDOM radio label keeps its right-slide via
# .slurm-max-option (original Max gif).
CUSTOM_CSS += f"""
/* Randomize-all popup — uses hobermanmax.gif (landscape) with Bob's
   bottom-up spring animation. */
.slurm-max-popup {{
    position: relative;
    overflow: visible !important;
}}
.slurm-max-popup::after {{
    content: "";
    position: absolute;
    /* Anchored at button bottom — rises straight up out of the button. */
    bottom: 0;
    left: 50%;
    transform: translateX(-50%) translateY(20px) scale(0.6);
    transform-origin: bottom center;
    /* Hoberman-Max source is 371x307 landscape — preserve aspect at display. */
    width: 145px;
    height: 120px;
    background-image: url("data:image/gif;base64,{_HOBERMAN_GIF_B64}");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: bottom center;
    opacity: 0;
    pointer-events: none;
    /* Same bouncy spring as Bob for matched motion. */
    transition: opacity 0.18s ease,
                transform 0.42s cubic-bezier(0.34, 1.56, 0.64, 1);
    z-index: 9999;
    filter: drop-shadow(0 6px 16px rgba(0,0,0,0.55));
}}
.slurm-max-popup:hover::after {{
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(1);
}}
"""



# ── Compact form controls — chip-row radios, dark dropdowns, slim drop zones ─
# Applied globally across ALL skins (default/acid/hardware) for radios,
# .slurm-dropdown, and .slurm-audio — none of the per-skin CSS overrides
# these, so universal rules are safe and produce a consistent look.
# (The default-skin-only block at the bottom keeps the info/gap tightening
#  scoped because Acid/Hardware deliberately use more generous spacing.)
CUSTOM_CSS += """
/* ═══════════════════════════════════════════════════════════════════════
   COMPACT FORM CONTROLS — global (all skins)
   • gr.Radio renders as a fieldset with one <label> per option. We restyle
     as a tight chip row, hide the native dot (cyan-bordered fill is the
     selection cue), and let labels wrap naturally.
   • gr.Dropdown's actual visible white box is hard to target generically;
     we add elem_classes=["slurm-dropdown"] to each Dropdown and force every
     descendant dark via the universal selector — bypasses class-name guessing.
   • gr.Audio's empty-state drop zone is ~400px tall by default; we add
     elem_classes=["slurm-audio"] and aggressively shrink min-height/padding/
     icon. Once audio loads, the waveform sets its own height — only the
     empty placeholder is affected.
   ═══════════════════════════════════════════════════════════════════════ */

/* ── Radio: chip-row layout ──────────────────────────────────────────── */
.gradio-container fieldset {
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
    background: transparent !important;
}
.gradio-container fieldset > .wrap,
.gradio-container [role="radiogroup"] {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 4px !important;
}
.gradio-container fieldset label,
.gradio-container [role="radiogroup"] label {
    background: #0e0c0c !important;
    border: 1px solid #2a2323 !important;
    border-radius: 4px !important;
    padding: 3px 9px !important;
    min-height: unset !important;
    min-width: unset !important;
    height: auto !important;
    font-size: 0.78rem !important;
    line-height: 1.5 !important;
    color: #8a8080 !important;
    cursor: pointer;
    transition: color 0.12s, border-color 0.12s, background 0.12s;
    box-shadow: none !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 0 !important;
}
.gradio-container fieldset label:hover,
.gradio-container [role="radiogroup"] label:hover {
    color: #cdc6c6 !important;
    border-color: #00b9e1 !important;
}
.gradio-container fieldset label:has(input:checked),
.gradio-container [role="radiogroup"] label:has(input:checked) {
    background: #0d2730 !important;
    border-color: #00b9e1 !important;
    color: #00b9e1 !important;
}
.gradio-container fieldset label input[type="radio"],
.gradio-container [role="radiogroup"] label input[type="radio"] {
    display: none !important;
}
.gradio-container .slurm-max-option {
    padding-left: 11px !important;
    padding-right: 11px !important;
}

/* Kill the scrollbar Gradio puts on the radio wrapper. With chip-row
   layout the chips wrap naturally so vertical scroll is unnecessary. */
.gradio-container fieldset,
.gradio-container [role="radiogroup"],
.gradio-container .gradio-radio,
.gradio-container [data-testid="radio-component"],
.gradio-container [data-testid*="radio"] {
    overflow: visible !important;
    max-height: none !important;
}
/* Also unconstrain the block wrapper that contains the radio */
.gradio-container .block:has(> fieldset),
.gradio-container .block:has([role="radiogroup"]) {
    overflow: visible !important;
    max-height: none !important;
}

/* ── Dropdown: dark theme + compact (via elem_classes=["slurm-dropdown"]) ─ */
.gradio-container .slurm-dropdown,
.gradio-container .slurm-dropdown * {
    background-color: #0e0c0c !important;
    color: #cdc6c6 !important;
    border-color: #2a2323 !important;
    box-shadow: none !important;
}
.gradio-container .slurm-dropdown {
    background-color: transparent !important;
}
.gradio-container .slurm-dropdown > .wrap,
.gradio-container .slurm-dropdown .wrap-inner,
.gradio-container .slurm-dropdown .container {
    background-color: #0e0c0c !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    padding: 3px 8px !important;
    min-height: 30px !important;
}
.gradio-container .slurm-dropdown input,
.gradio-container .slurm-dropdown [role="combobox"],
.gradio-container .slurm-dropdown [role="textbox"] {
    background: transparent !important;
    color: #cdc6c6 !important;
    font-size: 0.82rem !important;
    padding: 0 !important;
    min-height: unset !important;
    height: auto !important;
}
.gradio-container .slurm-dropdown svg {
    background: transparent !important;
    color: #6a6060 !important;
    fill: currentColor !important;
}
/* Popup options list (rendered in document body, not inside the wrapper) */
.gradio-container .options,
.gradio-container ul[role="listbox"],
body > .options,
body > ul[role="listbox"] {
    background: #161314 !important;
    border: 1px solid #2a2323 !important;
    border-radius: 5px !important;
    box-shadow: 0 6px 18px rgba(0,0,0,0.5) !important;
    color: #cdc6c6 !important;
}
.gradio-container .options .item,
.gradio-container .options li,
.gradio-container ul[role="listbox"] li,
body > .options .item,
body > ul[role="listbox"] li {
    color: #cdc6c6 !important;
    font-size: 0.82rem !important;
    padding: 4px 10px !important;
    background: transparent !important;
}
.gradio-container .options .item:hover,
.gradio-container .options li:hover,
.gradio-container ul[role="listbox"] li:hover,
body > .options .item:hover,
body > ul[role="listbox"] li:hover {
    background: #1e1a1b !important;
    color: #00b9e1 !important;
}
.gradio-container .options .selected,
.gradio-container ul[role="listbox"] [aria-selected="true"],
body > .options .selected,
body > ul[role="listbox"] [aria-selected="true"] {
    background: #0d2730 !important;
    color: #00b9e1 !important;
}

/* ── Audio drop zone: kill min-height, let Gradio size naturally ─────── */
/* Earlier attempts used max-height to cap empty-state size, but that
   clipped the transport controls (play/time/skip) on loaded audio. Now
   we just remove min-height so the empty state can shrink, keep tight
   padding, and let Gradio's natural sizing handle the loaded state.
   Output components keep transport controls when audio is loaded. */
.gradio-container .slurm-audio {
    min-height: 0 !important;
}
.gradio-container .slurm-audio > * {
    min-height: 0 !important;
}
.gradio-container .slurm-audio svg {
    width: 22px !important;
    height: 22px !important;
}
.gradio-container .slurm-audio .or,
.gradio-container .slurm-audio [class*="or"] {
    margin: 0 !important;
    font-size: 0.72rem !important;
    line-height: 1.15 !important;
}

/* ═══════════════════════════════════════════════════════════════════════
   DEFAULT SKIN ONLY: tighten vertical rhythm
   Acid + Hardware skins use more generous spacing on purpose.
   ═══════════════════════════════════════════════════════════════════════ */
body[data-skin="default"] .gradio-container .info,
body[data-skin="default"] .gradio-container [class*="info"] {
    font-size: 0.65rem !important;
    margin-top: 1px !important;
    margin-bottom: 3px !important;
    line-height: 1.25 !important;
}
body[data-skin="default"] .gradio-container .gap.column,
body[data-skin="default"] .gradio-container .form > .form,
body[data-skin="default"] .gradio-container [class*="column"] > .gap {
    gap: 4px !important;
}
"""


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


# ── Subvoyant icon baked at build time ───────────────────────────────────
_ICON_B64 = "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"
_ICON_TAG  = (
    '<a href="https://www.subvoyant.com" target="_blank" '
    'rel="noopener noreferrer" class="slurm-header-link" '
    'aria-label="Visit subvoyant.com">'
    '<img src="data:image/png;base64,' + _ICON_B64 +
    '" class="slurm-icon" alt="Subvoyant" />'
    '</a>'
)


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
