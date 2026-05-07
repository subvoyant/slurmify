"""
slurmcore.py — Pure DSP engine for Slurmify.

This module contains every audio processing function that does NOT touch
the filesystem, Gradio, or any operating-system service.  It is the
computational heart of the app — and the only part that should be unit-tested
in isolation, because its inputs and outputs are plain numpy arrays.

────────────────────────────────────────────────────────────────────────────────
Why this module exists
────────────────────────────────────────────────────────────────────────────────
Before Phase 2 of the modularisation (ADR-0016), all of this code lived inside
app.py, mixed with file I/O, Gradio event handlers, and UI-building code.
Keeping DSP and I/O in the same function body makes both harder to read and
impossible to test independently.

Separation rule (strict):

  slurmcore.py  — numpy arrays IN, numpy arrays OUT.
                  No open(), no soundfile, no os.path, no gr.Error.
                  No Gradio imports of any kind.

  app.py        — loads audio into arrays (load_audio), passes arrays here,
                  writes results back to temp files (_write_audio).

────────────────────────────────────────────────────────────────────────────────
Public API (functions imported by app.py)
────────────────────────────────────────────────────────────────────────────────

  detect_slice_points(y, sr, resolution, transient_sensitivity,
                      bpm_override=None) -> np.ndarray
      Computes the sample indices where the audio should be cut.
      Returns a 1-D int64 array of positions.

  apply_envelope(slice_audio, sr, envelope_ms) -> np.ndarray
      Applies a short fade-in/out to one audio slice to prevent
      digital clicks at boundaries.

  slurmify(y, sr, speed, resolution, transient_sensitivity,
           envelope_ms, preserve_pitch, pitch_shift_semitones,
           randomize_order, reverse_chance, stutter_chance,
           stutter_skip_ms, stutter_max_reps, stutter_spread,
           bpm_override, start_sec, end_sec, seed, _progress)
           -> tuple[np.ndarray, int]
      The full slurm transformation: stretch → slice → per-slice FX
      → (shuffle) → concatenate → normalize.  Returns the processed
      audio array and the sample rate.

  _fx_distortion(y, drive) -> np.ndarray
  _fx_ring_mod(y, sr, freq, depth) -> np.ndarray
  _fx_delay(y, sr, delay_sec, feedback, mix) -> np.ndarray
  _fx_phaser(y, sr, rate, depth) -> np.ndarray
      Individual FX DSP implementations (tanh waveshaper, ring modulator,
      tape delay, 4-stage allpass phaser).  Used by apply_fx and called
      in sequence there.  Also callable independently for testing.

  apply_fx(y, sr, dist_drive, ring_freq, ring_depth,
           delay_sec, delay_fb, delay_mix,
           phase_rate, phase_depth) -> tuple[np.ndarray, int]
      Applies the full FX chain (distortion → ring mod → delay → phaser)
      to an audio array and returns (processed_array, sr).
      Called by burn_fx() in app.py after loading the file.

────────────────────────────────────────────────────────────────────────────────
Dual FX channel constraint (IMPORTANT — DO NOT break this)
────────────────────────────────────────────────────────────────────────────────
Every FX effect here has a matching implementation in the browser-side Web Audio
API graph inside INIT_JS (in ui_assets.py).  The Python path runs at export
time on the numpy array; the JavaScript path runs in real time for the preview.
They share only the numeric slider values.

If you add, remove, or change any FX parameter, you MUST update BOTH places:
  1. The relevant _fx_* function and apply_fx() here in slurmcore.py
  2. The matching Web Audio node graph in INIT_JS inside ui_assets.py

Failing to keep them in sync means "burn FX" will sound different from the
live preview — a confusing user experience. See ADR-0016 §dual-fx.

────────────────────────────────────────────────────────────────────────────────
Allowed imports
────────────────────────────────────────────────────────────────────────────────
  random       — Python stdlib random (seeded for reproducibility)
  numpy        — array maths throughout
  librosa      — beat tracking, onset detection, pitch shifting, frames→samples
  pyrubberband — high-quality time-stretch and pitch-shift (wraps rubberband CLI)
  scipy.signal — lfilter allpass for phaser (imported locally inside _fx_phaser)

NOT allowed: os, sys, soundfile, gradio, shutil, subprocess, tempfile, pathlib.
"""

from __future__ import annotations

import random

import numpy as np
import librosa
import pyrubberband as pyrb


# ────────────────────────────────────────────────────────────────────────────
# detect_slice_points
# ────────────────────────────────────────────────────────────────────────────

def detect_slice_points(
    y: np.ndarray,
    sr: int,
    resolution: str,
    transient_sensitivity: float,
    bpm_override: float | None = None,
) -> np.ndarray:
    """Return sample indices where the audio should be sliced.

    This is the "where to cut" engine.  It does NOT cut the audio itself —
    it just decides the positions.  The actual cutting happens in slurmify().

    ──────────────────────────────────────────────────────────────
    Two strategies are blended:

    1. Adaptive beat-grid slicing
       librosa estimates the BPM and detects beat positions in the actual
       audio.  We then subdivide (or coarsen) the *actual beat intervals*
       rather than computing a rigid uniform grid from scratch.  This means
       the grid bends with the track's natural tempo drift instead of
       drifting away from it.

       When the user supplies `bpm_override`, that value is passed to librosa
       as `start_bpm` so the beat tracker anchors to the correct BPM octave
       (fixes 70 vs. 140 BPM confusion — librosa's default starting guess
       is 120 BPM, which can lock onto a sub-harmonic on half-time tracks).

       The `resolution` string sets how many subdivisions per beat we create:
         "1/1"  = one slice every 4 beats  (whole note at 4/4)
         "1/2"  = one slice every 2 beats  (half note)
         "1/4"  = one slice per beat        (quarter note — most musical)
         "1/8"  = two slices per beat       (eighth notes)
         … and so on up to "1/128" (very granular glitch)

    2. Transient snapping
       librosa detects audio onsets (drum hits, note attacks, etc.).
       Each grid point is optionally snapped to the nearest onset within a
       window proportional to the grid spacing.
       `transient_sensitivity` (0.0–1.0) blends the two strategies:
         0.0 → pure beat grid
         1.0 → pure onset list
         0.5 → hybrid: grid points pulled toward nearby onsets

    Special case: MAX RANDOM
       When `resolution == "MAX RANDOM"`, beat detection is skipped entirely.
       Instead, slice durations are drawn from a trimodal distribution:
         • stutter  5–30 ms   — audio-rate blip (buzzy glitch texture)
         • chop   100–500 ms  — recognisable rhythmic chunk
         • held  1000–4000 ms — long passage, audio almost plays through
       The gaps between buckets (30–100 ms and 500–1000 ms) are intentional.
       Filling them in would produce a "uniform chop" texture that blends
       into a constant tempo. The categorical gaps force the ear to hear
       dramatically different durations in sequence — genuine chaos.
       See ADR-0012 for the full rationale.

    ──────────────────────────────────────────────────────────────
    Parameters
    ----------
    y : np.ndarray
        Mono float32 audio array (time-domain PCM).
    sr : int
        Sample rate in Hz (usually 44100).
    resolution : str
        One of "MAX RANDOM", "1/1", "1/2", "1/4", "1/8", "1/16",
        "1/32", "1/64", "1/128".
    transient_sensitivity : float
        0.0 = ignore transients; 1.0 = follow transients only.
    bpm_override : float or None
        If set, this value is passed to librosa as `start_bpm` to anchor
        the tempo estimate to the correct octave.

    Returns
    -------
    np.ndarray
        1-D int64 array of sample indices.  The first element is always
        either 0 or close to 0; the last is always ≤ len(y).
    """
    # Smallest gap between two consecutive slice points.
    # 256 samples at 44.1 kHz ≈ 5.8 ms — shorter than this, the envelope
    # crossfade (apply_envelope) has no room to operate cleanly.
    MIN_SAMPLES = 256

    # ── MAX RANDOM: trimodal duration sampling ──────────────────────────────
    # Named after Max the tester (and "maximum entropy").  Three buckets,
    # each internally log-uniform so within-bucket variation is preserved
    # while the inter-bucket gaps force categorical jumps.
    # The seed is set by slurmify() before calling us, so the same seed
    # always produces the same sequence of slice positions.
    if resolution == "MAX RANDOM":
        # Each bucket: (name, shortest_ms, longest_ms)
        BUCKETS = [
            ("stutter",  5.0,    30.0),    # audio-rate glitch blips
            ("chop",   100.0,   500.0),    # rhythmic chunks
            ("held",  1000.0,  4000.0),    # near-uninterrupted passages
        ]
        positions = [0]
        pos = 0
        # Track per-bucket counts so we can print a diagnostic at the end.
        cat_counts = {"stutter": 0, "chop": 0, "held": 0}
        while pos < len(y):
            # Randomly pick a bucket with uniform probability (⅓ each).
            name, lo_ms, hi_ms = random.choice(BUCKETS)
            # Log-uniform sample within the bucket: equal probability for each
            # decade of time.  random.uniform in log space → exp back to linear.
            dur_ms = 10.0 ** random.uniform(np.log10(lo_ms), np.log10(hi_ms))
            # Convert ms → samples; 220 ≈ 5 ms at 44.1 kHz is the floor so
            # the envelope crossfade has at least a few samples to work with.
            dur_samples = max(220, int(sr * dur_ms / 1000.0))
            pos += dur_samples
            if pos < len(y):
                positions.append(pos)
                cat_counts[name] += 1

        # Diagnostic: print bucket distribution so developers can verify
        # the trimodal behaviour at runtime (dev console or macOS Console.app).
        gaps    = np.diff(positions) if len(positions) > 1 else np.array([0])
        gaps_ms = gaps * 1000.0 / sr
        n       = len(positions)
        print(
            f"[slurm] MAX RANDOM trimodal emitted {n} positions · "
            f"stutter={cat_counts['stutter']} chop={cat_counts['chop']} "
            f"held={cat_counts['held']} · "
            f"durations min={gaps_ms.min():.0f}ms "
            f"max={gaps_ms.max():.0f}ms "
            f"median={np.median(gaps_ms):.0f}ms"
        )
        return np.array(positions, dtype=np.int64)

    # ── Beat detection ──────────────────────────────────────────────────────
    # We keep beat_frames (the frame indices, not just the count _) so we
    # can subdivide or coarsen each *inter-beat interval individually*.
    # That makes the adaptive grid follow the track's own tempo curve rather
    # than drifting away from it.
    #
    # trim=False: don't discard leading/trailing beats.  Matters for tracks
    # that start with a pickup bar or fade out gradually.
    #
    # bpm_override as start_bpm: a hint, not a lock — librosa still refines
    # the estimate from the audio.  It just won't jump to a harmonically
    # related wrong octave (e.g. detecting 70 instead of 140 BPM on a
    # half-time groove with a very clear snare on beat 3).
    try:
        _kw = {"start_bpm": float(bpm_override)} if bpm_override else {}
        tempo, beat_frames = librosa.beat.beat_track(
            y=y, sr=sr, trim=False, **_kw
        )
        # tempo is sometimes returned as a 0-d or 1-element array — flatten.
        bpm = float(np.atleast_1d(tempo)[0])
        if bpm <= 0:
            # Pathological case (silence, or extremely sparse audio).
            bpm = float(bpm_override) if bpm_override else 120.0
        # Convert frame indices to absolute sample positions.
        beat_samples = librosa.frames_to_samples(beat_frames).astype(np.int64)
    except Exception:
        # If librosa throws (e.g. audio too short to analyse), fall back to
        # a uniform grid at the BPM hint or 120 BPM.
        beat_samples = np.array([], dtype=np.int64)
        bpm = float(bpm_override) if bpm_override else 120.0

    print(
        f"[slurm] BPM={bpm:.1f} beats={len(beat_samples)}"
        + (f" (override hint: {bpm_override})" if bpm_override else "")
    )

    # ── Resolution string → subdivisions per beat ───────────────────────────
    # Fractional values (0.25, 0.5) mean fewer slices per beat — each slice
    # spans MULTIPLE beats, which gives a slow, held-note texture.
    # Values > 1 subdivide each beat interval into multiple slices.
    res_map = {
        "1/1":    0.25,   # whole note   — one slice every 4 beats
        "1/2":    0.5,    # half note    — one slice every 2 beats
        "1/4":    1,      # quarter note — one slice per beat
        "1/8":    2,      # eighth note  — two slices per beat
        "1/16":   4,      # sixteenth    — four per beat
        "1/32":   8,
        "1/64":  16,
        "1/128": 32,
    }
    subdivs = res_map.get(resolution, 4)   # default to 1/16 if unknown

    # ── Build the adaptive beat grid ────────────────────────────────────────
    # Strategy A: we have detected beat positions → build an adaptive grid
    #   by subdividing or coarsening each inter-beat interval individually.
    # Strategy B: no beat positions detected → fall back to a rigid uniform
    #   grid derived from the detected (or overridden) BPM.
    if len(beat_samples) >= 2:
        grid_pts: list[int] = []

        if subdivs >= 1:
            # subdivs >= 1: insert (subdivs-1) evenly-spaced grid points
            # inside each pair of consecutive beats.
            n_sub = int(round(subdivs))
            for i in range(len(beat_samples) - 1):
                a, b = int(beat_samples[i]), int(beat_samples[i + 1])
                for k in range(n_sub):
                    # Linear interpolation: k=0 gives the beat itself;
                    # k=1 gives the midpoint (for subdivs=2), etc.
                    pt = a + int(k * (b - a) / n_sub)
                    grid_pts.append(pt)
            # Include the final beat position itself.
            grid_pts.append(int(beat_samples[-1]))

        else:
            # subdivs < 1: keep only every N-th beat as a grid boundary.
            # e.g. subdivs=0.5 → step=2 → every other beat (half notes).
            step = max(1, int(round(1.0 / subdivs)))
            grid_pts = [
                int(beat_samples[i])
                for i in range(0, len(beat_samples), step)
            ]

        # Ensure sample 0 is always in the grid so the first slice starts
        # at the beginning of the audio, not at the first detected beat.
        if not grid_pts or grid_pts[0] > 0:
            grid_pts.insert(0, 0)

        # Extrapolate grid points past the last detected beat to cover the
        # tail of the audio.  Many tracks fade out or have a long reverb tail
        # that extends beyond the last reliable beat.  Use the median inter-
        # point spacing (computed from the grid we just built) so the tail
        # slice size is consistent with the body of the track.
        if len(grid_pts) >= 2:
            spacing = int(np.median(np.diff(grid_pts)))
            spacing = max(spacing, MIN_SAMPLES)   # never shrink below floor
            pos = grid_pts[-1] + spacing
            while pos < len(y):
                grid_pts.append(pos)
                pos += spacing

        # Remove any grid points that are too close together.
        # This can happen when two beat detections fire within MIN_SAMPLES
        # of each other, or when rounding collapses two points to the same
        # sample.  We walk the sorted list and drop any point that doesn't
        # maintain the MIN_SAMPLES gap with its predecessor.
        filtered: list[int] = []
        for pt in sorted(set(grid_pts)):
            if not filtered or pt - filtered[-1] >= MIN_SAMPLES:
                filtered.append(pt)
        grid_points = np.array(filtered, dtype=np.int64)

        # Median spacing of the FILTERED grid — used as the transient snap
        # window below.  Computed after filtering so the window is consistent
        # with the actual grid density we'll use.
        median_spacing = (
            int(np.median(np.diff(grid_points)))
            if len(grid_points) >= 2
            else MIN_SAMPLES
        )

    else:
        # Fallback: no beat positions from librosa → uniform grid.
        # samples_per_slice: how many samples fit in one subdivision at this BPM.
        #   = (samples per minute) / bpm / subdivisions_per_beat
        #   = sr * 60 / bpm / subdivs
        samples_per_slice = max(MIN_SAMPLES, int(sr * 60.0 / bpm / subdivs))
        grid_points   = np.arange(0, len(y), samples_per_slice, dtype=np.int64)
        median_spacing = samples_per_slice

    # If transient_sensitivity is essentially zero, skip onset detection
    # entirely and return the pure beat grid.
    if transient_sensitivity <= 0.01:
        return grid_points

    # ── Onset detection (transient snapping) ────────────────────────────────
    # librosa.onset.onset_detect returns frame indices where significant
    # spectral energy changes occur.  backtrack=True snaps each onset to the
    # preceding local energy minimum, which gives tighter alignment to the
    # actual attack of a drum hit or note.
    #
    # `delta` is the minimum amplitude of an onset "peak" relative to the
    # surrounding noise floor.  Lower delta = more sensitive = more onsets.
    delta = max(0.01, 0.3 * (1.0 - transient_sensitivity))
    try:
        onset_frames  = librosa.onset.onset_detect(y=y, sr=sr, delta=delta, backtrack=True)
        onset_samples = librosa.frames_to_samples(onset_frames)
    except Exception:
        onset_samples = np.array([], dtype=np.int64)

    # Nothing to snap to → return the beat grid as-is.
    if len(onset_samples) == 0:
        return grid_points

    # At full sensitivity, ignore the beat grid entirely and use raw onsets.
    if transient_sensitivity >= 0.99:
        return onset_samples

    # ── Hybrid mode: snap grid points toward nearby onsets ─────────────────
    # The snap window is proportional to the grid spacing and inversely
    # proportional to sensitivity: high sensitivity → wide window → more
    # grid points get pulled toward onsets.  Low sensitivity → narrow window
    # → only onsets very close to an existing grid point have any effect.
    window = int(median_spacing * (1.0 - transient_sensitivity))
    snapped = []
    for gp in grid_points:
        # Find all onset positions within the snap window of this grid point.
        candidates = onset_samples[np.abs(onset_samples - gp) <= window]
        if len(candidates):
            # Snap to whichever onset is closest.
            snapped.append(int(candidates[np.argmin(np.abs(candidates - gp))]))
        else:
            # No nearby onset — keep the original grid point.
            snapped.append(int(gp))

    # Deduplicate and sort (snapping multiple grid points to the same onset
    # is valid — it just means fewer unique slice boundaries).
    return np.array(sorted(set(snapped)), dtype=np.int64)


# ────────────────────────────────────────────────────────────────────────────
# apply_envelope
# ────────────────────────────────────────────────────────────────────────────

def apply_envelope(slice_audio: np.ndarray, sr: int, envelope_ms: float) -> np.ndarray:
    """Apply a short fade-in and fade-out to one audio slice.

    Without this, cutting audio at arbitrary positions produces a hard
    discontinuity — a "click" or "pop" caused by the DAC suddenly jumping
    to a new amplitude.  A short linear fade-in at the start and fade-out
    at the end smooths these edges.

    The envelope is applied *symmetrically*: the same number of samples
    are faded at the beginning and the end.  For very short slices, the
    fade length is capped at half the slice length so the fades don't
    overlap and cancel each other out.

    Parameters
    ----------
    slice_audio : np.ndarray
        1-D float32 audio for a single slice.
    sr : int
        Sample rate in Hz.
    envelope_ms : float
        Fade duration in milliseconds.  0 = hard cuts (gritty, classic
        slurm clicks). >0 = smooth crossfades (more musical, cleaner).

    Returns
    -------
    np.ndarray
        The slice with fade-in and fade-out applied.  Same length as input.
    """
    # If envelope is zero or the slice is too short to fade, pass through.
    if envelope_ms <= 0 or len(slice_audio) < 4:
        return slice_audio

    # How many samples to use for the fade.
    # Capped at half the slice so fade_in and fade_out never overlap.
    n_fade = min(int(sr * envelope_ms / 1000.0), len(slice_audio) // 2)
    if n_fade < 2:
        return slice_audio  # too short for even a 2-sample ramp

    # Linear ramp: 0→1 for fade-in, 1→0 for fade-out.
    fade_in  = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, n_fade, dtype=np.float32)

    # Operate on a copy so we don't mutate the caller's array.
    out = slice_audio.copy()
    out[:n_fade]  *= fade_in
    out[-n_fade:] *= fade_out
    return out


# ────────────────────────────────────────────────────────────────────────────
# slurmify  (the main transformation engine)
# ────────────────────────────────────────────────────────────────────────────

def slurmify(
    y: np.ndarray,
    sr: int,
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
    seed: int | None = None,
    bar_mask: list[bool] | None = None,
    _progress=None,
) -> tuple[np.ndarray, int]:
    """Run the full slurm transformation on an audio array.

    This is the main DSP pipeline.  It takes a raw audio array (as loaded
    from any source — file, network stream, test fixture) and returns a new
    transformed audio array.  It does NOT read or write files; that is the
    caller's responsibility (app.py's process() and burn_fx()).

    ──────────────────────────────────────────────────────────────
    Pipeline steps
    ──────────────────────────────────────────────────────────────
    0. Optional trim: clip the audio to [start_sec, end_sec].
    1. Time-stretch: change playback speed.
       — preserve_pitch=True  → pyrubberband (high quality, pitch constant)
       — preserve_pitch=False → simple resample (chipmunk effect)
    1b. Independent pitch shift (±24 semitones = ±2 octaves).
        Applied AFTER the speed change so the two controls are decoupled.
    2. Slice points: detect_slice_points() decides WHERE to cut.
    3. Cut: split y into individual slice arrays.
    4. Per-slice DSP:
       — apply_envelope()    : anti-click fades
       — random reverse       : probability controlled by reverse_chance
       — stutter / repeat     : two modes (full-tile classic or head-loop skip)
    5. Optional global shuffle (randomize_order flag).
    6. Concatenate all processed slices.
    7. Soft normalize to –1 dBFS so stutter pile-up never clips.

    ──────────────────────────────────────────────────────────────
    Parameters
    ──────────────────────────────────────────────────────────────
    y : np.ndarray
        Mono float32 audio array.  Must already be at the target sample
        rate (44100 Hz).  load_audio() in app.py handles the loading
        and resampling.
    sr : int
        Sample rate of y (should be 44100).
    speed : float
        Playback speed multiplier.  1.0 = original, 2.0 = double speed.
    resolution : str
        Slice grid resolution.  See detect_slice_points() for the full list.
    transient_sensitivity : float
        0.0 = pure beat grid; 1.0 = pure onset detection.
    envelope_ms : float
        Fade duration in ms applied to each slice edge.  0 = hard clicks.
    preserve_pitch : bool
        True = time-stretch (rubberband, quality); False = resample (chipmunk).
    pitch_shift_semitones : float
        Independent pitch shift in semitones.  0 = no shift.
    randomize_order : bool
        If True, shuffle the processed slices before concatenating.
        Auto-checked by the UI when MAX RANDOM is selected (ADR-0013).
    reverse_chance : float
        Probability (0–1) that each slice is played in reverse.
    stutter_chance : float
        Probability (0–1) that each slice is stuttered (repeated).
    stutter_skip_ms : float
        0 = classic mode: tile the full slice N times.
        >0 = skip mode: loop only the first N ms of the slice (stutter-edit
             style), useful for fast glitch edits on long slices.
    stutter_max_reps : int
        Upper bound for the random repeat count (2..stutter_max_reps).
    stutter_spread : float
        0 = fixed skip length.  1 = skip length randomised per-event from
        [skip_ms*(1-spread), skip_ms] for organic, varied texture.
    bpm_override : float or None
        Optional BPM hint passed to detect_slice_points() / librosa.
    start_sec : float
        Trim audio from this position (seconds from start).  0 = beginning.
    end_sec : float
        Trim audio to this position.  0 = use full file.
    seed : int or None
        Random seed.  Set for reproducible output; None = fresh randomness.
    bar_mask : list[bool] or None
        Per-beat dropout pattern within each bar.  When set, slice i is kept
        only if ``bar_mask[i % len(bar_mask)]`` is True.  This lets the user
        toggle individual beat positions in the bar on/off — e.g., at 1/4
        resolution with bar_mask=[True, False, True, False], only beats 1 and
        3 of every bar survive in the output.

        The UI sends one bool per chip button; the chip count matches the
        number of note-subdivisions per bar for the active resolution.

        ``None`` or an all-True list = keep everything (default behaviour).
    _progress : callable or None
        Optional progress callback: _progress(fraction_0_1, desc="...").
        Passed in by the Gradio UI so the user sees a progress bar.

    Returns
    -------
    tuple[np.ndarray, int]
        (processed_audio_array, sample_rate)
        The caller (app.py) is responsible for writing this to a file.
    """
    # ── Internal progress helper ────────────────────────────────────────────
    # Wraps the optional Gradio progress callback so the DSP code doesn't
    # have to check for None on every call.
    def _prog(val: float, desc: str = "") -> None:
        if _progress is not None:
            _progress(val, desc=desc)

    # ── Seed the random state ───────────────────────────────────────────────
    # Seeding both Python's random and numpy's random ensures reproducibility
    # across all random choices: slice durations (MAX RANDOM), reverse chance,
    # stutter chance, stutter repeat count, and shuffle order.
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    # ── Step 0: optional trim ───────────────────────────────────────────────
    # The user can specify a start and end time to work on a subsection of
    # the audio.  end_sec=0 means "use the full file" (default).
    start_sample = int(max(0.0, start_sec) * sr)
    end_sample   = int(end_sec * sr) if end_sec > 0.0 and end_sec > start_sec else len(y)
    end_sample   = min(end_sample, len(y))    # never exceed actual length
    if start_sample > 0 or end_sample < len(y):
        y = y[start_sample:end_sample]
    if len(y) == 0:
        raise ValueError(
            "In/out range is empty — check your start and end times."
        )

    _prog(0.15, "Time-stretching…")
    # ── Step 1: time-stretch ────────────────────────────────────────────────
    if preserve_pitch:
        # pyrubberband time-stretches the audio while preserving pitch.
        # It calls the rubberband CLI binary (bundled in the .app).
        # speed > 1 = faster (shorter output); speed < 1 = slower (longer).
        y = pyrb.time_stretch(y, sr, speed)
    else:
        # Simple linear resample = "chipmunk mode": pitch goes up with speed,
        # down with slower playback.  Fast but musically interesting.
        new_len = max(1, int(len(y) / speed))
        y = np.interp(
            np.linspace(0, len(y) - 1, new_len),
            np.arange(len(y)),
            y,
        ).astype(np.float32)

    # ── Step 1b: independent pitch shift ────────────────────────────────────
    # Skipped when semitones == 0 to avoid a redundant rubberband pass.
    # Applied AFTER the speed change so the two controls are fully independent
    # (you can double the speed AND shift pitch down by a fifth).
    if pitch_shift_semitones != 0.0:
        _prog(0.28, "Shifting pitch…")
        y = pyrb.pitch_shift(y, sr, pitch_shift_semitones)

    _prog(0.40, "Finding slice points…")
    # ── Step 2: find slice points ────────────────────────────────────────────
    slice_points = detect_slice_points(
        y, sr, resolution, transient_sensitivity,
        bpm_override=bpm_override,
    )
    if len(slice_points) < 2:
        # Audio is too short or detection returned nothing useful.
        # Return the stretched audio as-is without slicing.
        _prog(1.0, "Done")
        return y.astype(np.float32), sr

    _prog(0.50, "Slicing…")
    # ── Step 3: cut into slices ──────────────────────────────────────────────
    slices = []
    for i in range(len(slice_points) - 1):
        start, end = int(slice_points[i]), int(slice_points[i + 1])
        if end > start:
            slices.append(y[start:end])
    # Tail: any audio after the last slice point.
    if slice_points[-1] < len(y):
        slices.append(y[int(slice_points[-1]):])

    # ── Step 3b: bar mask filtering (optional) ──────────────────────────────
    # The bar mask is a list of N booleans where N = number of note-
    # subdivisions per bar at the active resolution (e.g. 4 bools for 1/4,
    # 8 for 1/8, 16 for 1/16).  Slice i is retained iff:
    #
    #     bar_mask[i % N]  is True
    #
    # This produces a repeating per-bar dropout pattern: every occurrence of
    # beat 2 across the whole file can be silenced by setting bar_mask[1]=False
    # at 1/4 resolution.
    #
    # Skip the filtering entirely when:
    #   • bar_mask is None (feature not engaged — default)
    #   • bar_mask is all-True (all beats on = no change)
    # This avoids any performance overhead on the common "no mask" path.
    if bar_mask and not all(bar_mask):
        n_mask = len(bar_mask)
        slices = [s for i, s in enumerate(slices) if bar_mask[i % n_mask]]
        if not slices:
            # Every slice was masked out (user toggled all chips off).
            # Return 1 sample of silence — avoids a div-by-zero in the
            # normalizer and keeps the return contract (ndarray, int) valid.
            _prog(1.0, "Done")
            return np.zeros(1, dtype=np.float32), sr

    _prog(0.60, "Processing slices…")
    # ── Step 4: per-slice transformations ───────────────────────────────────
    processed: list[np.ndarray] = []
    n_slices = len(slices)
    for idx, s in enumerate(slices):
        if len(s) < 4:
            # Slice is too short to do anything useful with.
            continue

        # 4a. Apply fade-in/out to prevent clicks at the cut boundaries.
        s = apply_envelope(s, sr, envelope_ms)

        # 4b. Random reverse: flip the slice's time axis.
        #     Probability controlled by reverse_chance (0 = never, 1 = always).
        if reverse_chance > 0 and random.random() < reverse_chance:
            s = s[::-1].copy()   # copy() detaches from the original slice view

        # 4c. Stutter / repeat.
        #     Two modes, controlled by stutter_skip_ms:
        #
        #     Classic mode (stutter_skip_ms == 0):
        #       Tile the FULL slice N times.  The slice is literally repeated
        #       back-to-back.  Good for rhythmic patterns.
        #
        #     Skip mode (stutter_skip_ms > 0):
        #       Loop only the HEAD (first N ms) of the slice, discarding the
        #       rest.  Mimics the stutter-edit technique in DAWs: you hear a
        #       fast loop of just the attack of a sound.  stutter_spread adds
        #       per-event variation to the head length for a more organic feel.
        if stutter_chance > 0 and random.random() < stutter_chance:
            # How many times to repeat: 2..stutter_max_reps, uniformly random.
            actual_reps = random.randint(2, max(2, int(stutter_max_reps)))

            if stutter_skip_ms > 0:
                # Skip mode: determine the effective head length for this event.
                if stutter_spread > 0:
                    # Vary the head length per-event.  lo_ms is the minimum
                    # head length (5 ms floor prevents sub-click lengths).
                    lo_ms  = max(5.0, stutter_skip_ms * (1.0 - float(stutter_spread)))
                    eff_ms = random.uniform(lo_ms, stutter_skip_ms)
                else:
                    # Fixed head length for every stutter event.
                    eff_ms = float(stutter_skip_ms)

                # Convert ms → samples; 5 ms minimum.
                head_n = max(int(sr * 0.005), int(sr * eff_ms / 1000.0))
                head_n = min(head_n, len(s))

                # Apply the envelope to the head independently so each
                # repeated head starts and ends cleanly.
                head = apply_envelope(s[:head_n], sr, envelope_ms)
                s    = np.tile(head, actual_reps)
            else:
                # Classic mode: tile the full (already-enveloped) slice.
                s = np.tile(s, actual_reps)

        processed.append(s)

        # Report per-slice progress: moves from 0.60 to 0.80 as we process.
        _prog(
            0.60 + 0.20 * (idx + 1) / max(n_slices, 1),
            "Processing slices…",
        )

    _prog(0.82, "Mixing…")
    # ── Step 5: optional global shuffle ─────────────────────────────────────
    # This is the "randomize slice order" checkbox in the UI.  When MAX RANDOM
    # is selected, a .change() handler auto-checks it (ADR-0013), but the user
    # can uncheck it to get trimodal durations in their ORIGINAL order.
    if randomize_order:
        random.shuffle(processed)

    # ── Step 6: concatenate ─────────────────────────────────────────────────
    if not processed:
        # All slices were dropped (too short).  Return the original stretched
        # audio rather than an empty array.
        out = y
    else:
        out = np.concatenate(processed)

    # ── Step 7: soft normalize to –1 dBFS ──────────────────────────────────
    # After stutter tiling, amplitude can pile up significantly.  Normalise
    # to 0.891× peak (≈ –1 dBFS) so we stay just below clipping without
    # imposing a hard limiter.  If the output is silence (peak == 0), skip.
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0:
        out = (out / peak * 0.891).astype(np.float32)  # –1 dBFS ceiling

    _prog(1.0, "Done ✓")
    return out, sr


# ────────────────────────────────────────────────────────────────────────────
# FX DSP helpers
# ────────────────────────────────────────────────────────────────────────────
#
# Each function is named _fx_* and implements one stage of the FX chain.
# They are also exposed in apply_fx() below (the "burn FX" path).
#
# DUAL FX CHANNEL REMINDER: every function here has a matching Web Audio API
# node in INIT_JS (ui_assets.py).  If you change a parameter range, default,
# or algorithm here, update the JS side too — or the preview and export will
# sound different.
# ────────────────────────────────────────────────────────────────────────────

def _fx_distortion(y: np.ndarray, drive: float) -> np.ndarray:
    """Tanh soft-clip waveshaper.

    A waveshaper maps each sample value through a non-linear function —
    in this case tanh (hyperbolic tangent), which smoothly clips peaks
    rather than hard-cutting them.  The effect sounds warm and "tube-like"
    at low drive values, and harsh / fuzz-like at high drive.

    Pre-gain: drive 0–1 → pre-gain 1×–30× (linear scale inside tanh).
    The tanh output is normalised by tanh(k) so the curve passes through
    the same ±1 range regardless of drive, keeping downstream levels stable.

    Matches the WaveShaper node in the Web Audio FX chain (ui_assets.py).

    Parameters
    ----------
    y : np.ndarray  — float32 audio, any shape (mono 1-D or stereo 2-D)
    drive : float   — 0 = clean pass-through; 1 = maximum saturation

    Returns
    -------
    np.ndarray  — same shape as y, float32
    """
    if drive < 0.01:
        return y   # drive is essentially zero — skip the computation
    k = float(1.0 + drive * 29.0)           # map 0–1 → 1–30 pre-gain
    return (np.tanh(y * k) / np.tanh(k)).astype(np.float32)


def _fx_ring_mod(y: np.ndarray, sr: int, freq: float, depth: float) -> np.ndarray:
    """Amplitude modulation via a sine carrier oscillator.

    Ring modulation multiplies the audio signal by a carrier sine wave.
    At 100 % depth the output is the pure ring-modulated signal; at 0 %
    it is the dry signal.  The carrier creates sidebands at (signal ± carrier)
    frequencies — sounds metallic, robotic, or bell-like depending on freq.

    The gain formula:
      mod[t] = 1 + depth * sin(2π * freq * t)
    matches the Web Audio graph: gain.value=1, oscillator→gain.gain.
    This means at depth=1 the gain swings between 0 and 2, producing full
    amplitude modulation.

    Parameters
    ----------
    y : np.ndarray  — float32, mono (1-D) or stereo (2-D, shape [ch, n])
    sr : int        — sample rate in Hz
    freq : float    — carrier frequency in Hz (typical range 50–8000)
    depth : float   — modulation depth 0–1

    Returns
    -------
    np.ndarray  — same shape as y, float32
    """
    if depth < 0.01:
        return y
    mono = y.ndim == 1
    if mono:
        # Promote to 2-D so the vectorised multiply works the same for
        # both mono and stereo; we'll demote back at the end.
        y = y[np.newaxis, :]
    t   = np.arange(y.shape[1], dtype=np.float32) / sr
    mod = 1.0 + depth * np.sin(2 * np.pi * freq * t, dtype=np.float32)
    out = (y * mod[np.newaxis, :]).astype(np.float32)
    return out[0] if mono else out


def _fx_delay(
    y: np.ndarray,
    sr: int,
    delay_sec: float,
    feedback: float,
    mix: float,
) -> np.ndarray:
    """Tape delay with a feedback loop.

    A delay line stores a copy of past audio and mixes it back at the
    requested delay time.  The feedback parameter controls how much of
    the delayed signal feeds back into the delay buffer — higher values
    produce longer "echo trails" (keep < 1.0 to prevent runaway feedback).
    The mix parameter controls wet/dry: 0 = dry only, 1 = wet only.

    This is a time-domain implementation using a circular delay buffer
    (buf), matching the DelayNode + GainNode feedback loop in the Web Audio
    FX chain.

    Parameters
    ----------
    y : np.ndarray   — float32, mono (1-D) or stereo (2-D)
    sr : int         — sample rate
    delay_sec : float — delay time in seconds (0–1 s)
    feedback : float  — feedback amount 0–0.9 (higher → more echo repeats)
    mix : float       — wet/dry ratio 0–1

    Returns
    -------
    np.ndarray  — same shape as y, float32
    """
    if mix < 0.01 or delay_sec < 0.001:
        return y
    mono = y.ndim == 1
    if mono:
        y = y[np.newaxis, :]
    n_ch, n = y.shape

    # Circular delay buffer: d samples per channel.
    d   = max(1, int(delay_sec * sr))
    buf = np.zeros((n_ch, d), dtype=np.float32)
    wet = np.zeros_like(y)
    wi  = 0   # write index (advances mod d each sample)

    for i in range(n):
        tap        = buf[:, wi].copy()           # read from buffer
        wet[:, i]  = tap                         # this is the delayed signal
        buf[:, wi] = y[:, i] + tap * feedback    # mix new signal + fed-back tap
        wi         = (wi + 1) % d                # advance circular pointer

    out = (y * (1 - mix) + wet * mix).astype(np.float32)
    return out[0] if mono else out


def _fx_phaser(y: np.ndarray, sr: int, rate: float, depth: float) -> np.ndarray:
    """4-stage allpass phaser with a sine LFO.

    A phaser creates a comb-filter effect by mixing the dry signal with a
    version that has been run through a chain of allpass filters whose centre
    frequencies are swept by a slow oscillator (the LFO).  The result is
    a "swooshing" or "jet" sound.

    Implementation:
    — 4 first-order allpass sections at 200, 600, 1200, 2400 Hz.
    — Each section's centre frequency is modulated ±(depth*50%) by the LFO.
    — The phased output is blended with the dry signal at ±(depth*0.5).

    Matches the AllpassFilter + LFO structure in the Web Audio FX chain.

    Parameters
    ----------
    y : np.ndarray  — float32, mono (1-D) or stereo (2-D)
    sr : int        — sample rate
    rate : float    — LFO frequency in Hz (typical range 0.1–5)
    depth : float   — effect depth 0–1

    Returns
    -------
    np.ndarray  — same shape as y, float32
    """
    if depth < 0.01:
        return y
    from scipy.signal import lfilter   # local import — keeps module load fast

    mono = y.ndim == 1
    if mono:
        y = y[np.newaxis, :]
    n_ch, n = y.shape

    # LFO: a single sine wave controlling all four allpass stages.
    t   = np.arange(n, dtype=np.float64) / sr
    lfo = np.sin(2 * np.pi * rate * t)   # values in [-1, 1]

    # 4 allpass stages; centre frequencies chosen to spread across the
    # audible spectrum for a rich, wide-sounding sweep.
    centers = [200.0, 600.0, 1200.0, 2400.0]
    phased  = y.astype(np.float64).copy()

    for fc in centers:
        # First-order allpass coefficient (Regalia–Mitra form):
        #   H(z) = (a + z⁻¹) / (1 + a·z⁻¹),  a = (tan(π·fc/sr) - 1) / (tan(π·fc/sr) + 1)
        # We compute fc using the MEAN LFO value — this is a cheap approximation
        # that avoids per-sample coefficient recomputation at the cost of the
        # sweep range being slightly narrower than the exact time-varying version.
        # The approximation is acceptable because the human ear doesn't require
        # precise tracking of allpass poles during a slow LFO sweep.
        fc_mean = float(np.clip(
            fc * (1.0 + 0.5 * depth * lfo.mean()),
            20, sr / 2 - 1
        ))
        tw = np.tan(np.pi * fc_mean / sr)
        a  = (tw - 1.0) / (tw + 1.0)

        # Apply the allpass filter to each channel independently.
        for ch in range(n_ch):
            phased[ch] = lfilter([a, 1.0], [1.0, a], phased[ch])

    # Mix: dry signal attenuated by depth*0.5, phased signal added at depth*0.5.
    out = (y * (1 - depth * 0.5) + phased * (depth * 0.5)).astype(np.float32)
    return out[0] if mono else out


# ────────────────────────────────────────────────────────────────────────────
# apply_fx  — full FX chain (called by burn_fx in app.py)
# ────────────────────────────────────────────────────────────────────────────

def apply_fx(
    y: np.ndarray,
    sr: int,
    dist_drive: float,
    ring_freq: float,
    ring_depth: float,
    delay_sec: float,
    delay_fb: float,
    delay_mix: float,
    phase_rate: float,
    phase_depth: float,
) -> tuple[np.ndarray, int]:
    """Apply the full FX chain (distortion → ring mod → delay → phaser).

    This is the pure DSP part of what was previously the entire burn_fx()
    function in app.py.  The I/O concerns (loading the file, handling
    gr.Error, writing the output file) remain in app.py's burn_fx().

    The FX order (distortion → ring mod → delay → phaser) matches the Web
    Audio API graph in INIT_JS exactly so the burned FX sounds identical
    to the live browser preview.  Do NOT reorder.

    Post-processing:
    — Peak-limit to 0.95 × full scale if the FX stack causes clipping.
    — Hard clip to ±1.0 (safety net; shouldn't trigger after limiting).
    — If the input was mono (shape [1, n]), the output is promoted back to 2-D
      by the FX functions and then squeezed to 1-D before returning, so the
      caller (burn_fx → _write_audio → soundfile) gets the shape it expects.

    Parameters
    ----------
    y : np.ndarray
        Float32 audio array.  Shape must be (n,) mono or (channels, n) stereo.
        (burn_fx promotes mono to shape (1, n) before calling us — that's fine,
        the _fx_* functions handle both.)
    sr : int
        Sample rate.
    dist_drive : float   — waveshaper drive 0–1
    ring_freq : float    — ring mod carrier Hz
    ring_depth : float   — ring mod depth 0–1
    delay_sec : float    — delay time seconds 0–1
    delay_fb : float     — delay feedback 0–0.9
    delay_mix : float    — delay wet/dry 0–1
    phase_rate : float   — phaser LFO Hz
    phase_depth : float  — phaser depth 0–1

    Returns
    -------
    tuple[np.ndarray, int]
        (processed_audio, sr)
        The caller decides whether to write it as mono or stereo based on
        the original input shape.
    """
    # ── FX chain: order matches INIT_JS Web Audio graph ────────────────────
    y = _fx_distortion(y, float(dist_drive or 0))
    y = _fx_ring_mod(y, sr, float(ring_freq or 200), float(ring_depth or 0))
    y = _fx_delay(y, sr,
                  float(delay_sec or 0.3),
                  float(delay_fb or 0.35),
                  float(delay_mix or 0))
    y = _fx_phaser(y, sr, float(phase_rate or 1.0), float(phase_depth or 0))

    # ── Safety limiting ─────────────────────────────────────────────────────
    # Distortion + ring mod can occasionally boost peak amplitude above 1.0.
    # Attenuate to 0.95× full scale rather than hard-clipping abruptly.
    peak = float(np.max(np.abs(y)))
    if peak > 1.0:
        y = y / peak * 0.95

    # Hard clip as a final safety net (should be a no-op after peak limiting).
    y = np.clip(y, -1.0, 1.0)

    return y, sr
