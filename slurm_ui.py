"""
slurm_ui.py — Gradio UI orchestration for Slurmify.

Phase 4 of the modularisation (ADR-0018).  This module contains everything
that drives the Gradio interface:

  • burn_fx()       — Gradio event handler: load audio → DSP → write file
  • render_video()  — YouTube-ready MP4 export (ffmpeg-driven)
  • process()       — main slurmify pipeline (Gradio entry point)
  • _quit_app()     — graceful server shutdown from the browser
  • build_ui()      — constructs and returns the gr.Blocks layout
  • __version__     — canonical app version string
  • helper functions for filename mangling: _leetify, _jumble_name, _safe_title
  • module-level constants: _LEET_PAIRS, _AUDIO_EXTS

What this module does NOT do
────────────────────────────
  • No direct filesystem reads or writes — those go through slurmio.py.
    (_new_temp_path, _write_audio, load_audio, _asset are the only IO
    calls you'll see, and they're all delegated to slurmio.)
  • No pure-DSP computation — that lives in slurmcore.py.
  • No browser-side static assets (JS, CSS, base64 images) — those live
    in ui_assets.py.

How it fits the 4-module architecture
──────────────────────────────────────
  app.py       — bootstrap + PyInstaller path wiring + __main__ launch
  slurm_ui.py  — THIS FILE: Gradio layout + event handlers + video export
  slurmcore.py — pure audio DSP (numpy arrays in/out, no I/O, no Gradio)
  slurmio.py   — filesystem IO (load/write audio, session-temp directory)
  ui_assets.py — static browser content (JS, CSS, base64 GIF/PNG)

Import graph (no cycles):
  app.py → slurm_ui → slurmio / slurmcore / ui_assets
  Nothing imports from app.py or slurm_ui from within the other modules.

PyInstaller note
────────────────
"slurm_ui" must be listed in hiddenimports in slurmify.spec.  PyInstaller's
static analysis does not auto-detect local .py imports.  If that entry is
ever removed, the bundled .app will crash at startup with:
    ModuleNotFoundError: No module named 'slurm_ui'
"""

from __future__ import annotations

# ── Standard library ─────────────────────────────────────────────────────────
# All imports that were previously deferred (local `import foo` inside
# function bodies) are promoted here.  Keeping them at module-level makes
# the import graph explicit and removes the visual surprise of mid-function
# imports.
import json          # render_video: build + serialise the PATCH metadata blob
import os            # path existence checks, FFMPEG_BINARY env, os._exit
import random        # _jumble_name, _randomize_all (was `import random as _r`)
import shutil        # shutil.which — locate ffmpeg on PATH at call time
import subprocess    # ffmpeg invocations in _route_upload and render_video
import threading     # _quit_app: Timer so the response flushes before exit
from datetime import datetime, timezone  # render_video: timestamp + copyright year
from pathlib import Path                 # suffix extraction, stem mangling

# ── Third-party ──────────────────────────────────────────────────────────────
import gradio as gr       # the whole UI framework
import librosa            # burn_fx: load with native SR/channels preserved
import numpy as np        # burn_fx: shape manipulation before/after apply_fx

# ── Local: filesystem IO ─────────────────────────────────────────────────────
# Everything that touches the disk comes through slurmio.py so this module
# stays testable without a real filesystem and so all temp-file lifetime is
# managed centrally in one place (slurmio keeps the atexit hook and orphan
# sweeper).
from slurmio import (
    _asset,           # resolve bundled asset paths (dev vs. frozen bundle)
    _new_temp_path,   # create a session-scoped temp file (auto-wiped on exit)
    _reveal_temp_dir, # open the session temp dir in the OS file browser
    SUPPORTED_EXTS,   # frozenset of accepted audio/video file extensions
    load_audio,       # load any audio/video file → (ndarray, sr) at 44 100 Hz mono
    _write_audio,     # write audio ndarray → session-scoped temp file
)

# ── Local: pure DSP ───────────────────────────────────────────────────────────
# slurmcore.py is the DSP engine: numpy arrays in, numpy arrays out, no I/O,
# no Gradio.  We call slurmify() for the main chop pipeline and apply_fx()
# for the FX-burn path.
from slurmcore import (
    slurmify,   # main DSP pipeline: stretch → slice → FX → concat
    apply_fx,   # full FX chain (distortion → ring → delay → phaser)
)

# ── Local: static browser assets ─────────────────────────────────────────────
# _ICON_TAG is the only thing from ui_assets that build_ui() references
# directly — it's the pre-assembled <a><img> HTML for the header logo.
# INIT_JS, CUSTOM_CSS, _ICON_B64 stay in app.py's __main__ (they're
# injected into launch() rather than the layout).
from ui_assets import _ICON_TAG


# ── Version ──────────────────────────────────────────────────────────────────
# Single source of truth for the version string.  render_video() embeds it
# in the MP4 metadata.  The slurm-tag <div> in build_ui() hard-codes it too
# (Gradio HTML is a string, not an expression) — keep both in sync when
# bumping the version.  Also update build.sh and slurmify.spec.
__version__ = "0.1.6"


# ─────────────────────────────────────────────────────────────────────────────
# Filename-mangling helpers (used by render_video)
# ─────────────────────────────────────────────────────────────────────────────

# Look-alike letter/digit substitution table.  Each pair goes both ways so
# the substitution can be applied repeatedly and still find a match.
_LEET_PAIRS = {
    "e": "3", "3": "e",
    "s": "5", "5": "s",
    "o": "0", "0": "o",
    "i": "1", "1": "i",
}

# Extensions that the upload router treats as "already audio" and passes
# straight through to audio_in without ffmpeg extraction.  Everything else
# is treated as a video/container file and goes through ffmpeg -vn to pull
# the audio track.
_AUDIO_EXTS = frozenset({
    ".mp3", ".wav", ".aif", ".aiff", ".aac", ".m4a",
    ".flac", ".ogg", ".opus", ".wma", ".ape", ".alac",
})


# ─────────────────────────────────────────────────────────────────────────────
# Note-mode constants (ADR-0020)
# ─────────────────────────────────────────────────────────────────────────────
# The four MUSICAL time parameters (stutter_skip, beat_trim_start,
# beat_trim_end, beat_gap) each get a per-slider unit toggle ("ms ⇄ ♪")
# in the UI.  When the user picks "♪" mode, the slider is hidden and a
# Dropdown of note fractions takes its place.  The selected note string is
# converted to milliseconds inside slurmify() using detect_slice_points'
# returned BPM (single source of truth — see ADR-0020 §single-bpm).
#
# _NOTE_CHOICES is the same list for all four dropdowns so users see a
# consistent vocabulary.  The grammar is parsed by _note_to_ms in slurmcore:
#   "1/N"   straight subdivisions (1/64 → 1/2)
#   "1/N."  dotted (×1.5)
#   "1/NT"  triplet (×2/3)
#   "1"     whole note (4 beats)
#   "2"     two whole notes (8 beats — useful for long sparse gaps)
#
# At 120 BPM these correspond roughly to:
#   1/64 ≈ 31 ms · 1/32 ≈ 63 ms · 1/16 ≈ 125 ms · 1/8 ≈ 250 ms ·
#   1/4 = 500 ms · 1/2 = 1000 ms · 1 = 2000 ms · 2 = 4000 ms.
_NOTE_CHOICES = [
    "1/64",  "1/32",
    "1/16T", "1/16", "1/16.",
    "1/8T",  "1/8",  "1/8.",
    "1/4T",  "1/4",  "1/4.",
    "1/2",   "1",    "2",
]

# Default note value when the user first flips a slider into "♪" mode.
# 1/16 is a common chop length that matches the default slice resolution
# (also "1/16") so the result feels coherent on the first try.
_NOTE_DEFAULT = "1/16"

# Mode toggle choices.  The "♪" glyph (U+266A EIGHTH NOTE) renders
# legibly in every browser font we've tested without needing a fallback.
# Order matters — "ms" is the default so it appears first.
_UNIT_MODE_CHOICES = ["ms", "♪"]


def _swap_unit_mode(mode: str):
    """Visibility swap for a (slider, note_dropdown) pair driven by a mode radio.

    Returns two `gr.update(visible=...)` objects for the slider and the
    note dropdown respectively.  Wired to each unit-mode radio's `.change`
    event in build_ui() — Gradio applies the visibility update without a
    full page rerender so the swap is instant.

    The hint span next to each slider is updated client-side by JS in
    INIT_JS — keeping it out of this Python handler avoids a Python
    round-trip on every slider drag.

    Parameters
    ----------
    mode : str
        Either "ms" or "♪" (or anything else, treated as "ms").

    Returns
    -------
    tuple[gr.update, gr.update]
        (slider_visibility, dropdown_visibility) — exactly one of each
        pair is visible at any time.
    """
    if mode == "♪":
        return gr.update(visible=False), gr.update(visible=True)
    return gr.update(visible=True), gr.update(visible=False)


def _leetify(chars: list[str], rng: random.Random, prob: float = 0.5) -> list[str]:
    """Randomly transpose look-alike letter/digit pairs in a char list.

    For each character in `chars`, if it's in _LEET_PAIRS and a random draw
    is below `prob`, swap it for its look-alike (e.g. 'e' → '3', 's' → '5').
    Returns a NEW list; does not modify in place.

    Parameters
    ----------
    chars : list[str]
        Individual characters to potentially transpose.
    rng : random.Random
        Seeded RNG instance so the output is reproducible when a fixed seed
        was passed by the user.
    prob : float
        Probability that each eligible character gets transposed (default 0.5).
    """
    return [_LEET_PAIRS[c] if (c in _LEET_PAIRS and rng.random() < prob) else c
            for c in chars]


def _jumble_name(src_path: str, *, length: int = 16,
                 seed: int | None = None) -> str:
    """Turn a source filename into a chaotic, slurmified suffix.

    Algorithm:
      1. Strip the file extension; lowercase the stem.
      2. Keep only alphanumeric characters (drop spaces, punctuation).
      3. Shuffle the remaining characters with `rng`.
      4. Pad to `length` with random alphanumeric characters if too short.
      5. Trim to `length`.
      6. Randomly leet-transpose look-alike pairs (50% probability each).

    The result is 16 characters of pleasant chaos that still has a visual
    DNA connection to the original filename.

    The output is deterministic when `seed` is set (the user typed a seed in
    the UI), so a reproducible slurmify run also produces the same filename.

    Parameters
    ----------
    src_path : str
        Path to the original source file.  Only the stem (no extension) is used.
    length : int
        Target length of the suffix string (default 16).
    seed : int | None
        RNG seed.  None → freshly random each call.
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
    """Sanitize a user-typed title string so it can appear in a filename.

    Rules:
      • Lowercase everything.
      • Alphanumeric characters pass through unchanged.
      • Spaces, hyphens, and underscores become a single underscore.
      • All other characters are dropped.
      • Leading/trailing underscores are stripped.
      • Consecutive underscores are collapsed to one.
      • Result is capped at `max_len` characters.

    Parameters
    ----------
    s : str
        The raw title string from the Gradio textbox.
    max_len : int
        Maximum length of the cleaned string (default 40).
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Gradio event handlers
# ─────────────────────────────────────────────────────────────────────────────

def burn_fx(
    audio_path,
    dist_drive, ring_freq, ring_depth,
    delay_sec, delay_fb, delay_mix,
    phase_rate, phase_depth,
    out_fmt,
):
    """Gradio event handler: load audio from disk, apply FX chain, write output.

    This is the thin "glue" wrapper that bridges Gradio and the pure DSP layer
    in slurmcore.py.  The separation keeps slurmcore completely free of I/O
    and Gradio dependencies.

    Flow
    ────
      1. Validate the input path (raise gr.Error if missing — Gradio surfaces
         this as a friendly red banner rather than a raw Python traceback).
      2. Load the audio with librosa, preserving the original sample rate and
         channel layout (sr=None → keep native SR; mono=False → keep stereo).
         NOTE: we do NOT use load_audio() from slurmio here because load_audio
         forces mono + 44 100 Hz, which would corrupt the FX chain by discarding
         the stereo information and resampling.  librosa.load with sr=None and
         mono=False preserves the original signal faithfully.
      3. Ensure the array is 2-D (channels × samples) — the _fx_* functions in
         slurmcore.py expect that shape and handle mono/stereo themselves.
      4. Call apply_fx() from slurmcore — pure DSP, no I/O.
      5. Squeeze back to 1-D if the input was originally mono, so soundfile
         writes a proper mono file rather than a 1-channel stereo file.
      6. Write the result to a new temp file via _write_audio().

    Parameters match the Gradio slider names exactly (burn_btn.click wiring
    at the bottom of build_ui()).
    """
    # 1. Guard: nothing to apply FX to yet.
    if not audio_path or not os.path.exists(str(audio_path)):
        raise gr.Error("Run slurmify first — no output to apply FX to.")

    # 2. Load — preserve native sample rate and channel count.
    #    librosa returns mono 1-D or stereo 2-D depending on the file.
    #    We need the original layout intact so the FX chain doesn't collapse
    #    a stereo mix to mono or mis-apply the ring modulator.
    y, sr = librosa.load(audio_path, sr=None, mono=False)

    # 3. Promote to 2-D so apply_fx can handle mono and stereo uniformly.
    #    The _fx_* functions always return 2-D (channels × samples).
    #    We record whether the original was mono so we can squeeze back at step 5.
    was_mono = y.ndim == 1
    if was_mono:
        y = y[np.newaxis, :]   # (n,) → (1, n)
    y = y.astype(np.float32)  # _fx_* functions expect float32

    # 4. Pure DSP — no I/O, no gr.Error inside here.
    y, sr = apply_fx(
        y, sr,
        dist_drive  = float(dist_drive  or 0),
        ring_freq   = float(ring_freq   or 200),
        ring_depth  = float(ring_depth  or 0),
        delay_sec   = float(delay_sec   or 0.3),
        delay_fb    = float(delay_fb    or 0.35),
        delay_mix   = float(delay_mix   or 0),
        phase_rate  = float(phase_rate  or 1.0),
        phase_depth = float(phase_depth or 0),
    )

    # 5. Convert back to soundfile's expected layout (ADR-0021):
    #      mono   → shape (n,)
    #      stereo → shape (n, channels)
    #    apply_fx returns (channels, n) — slurmcore's channels-FIRST
    #    convention — so for stereo we need a `.T` transpose.  Mono was
    #    promoted to (1, n) in step 3 and gets squeezed back to (n,) here.
    #
    #    NOTE: this used to leave stereo as (2, n) — that was a latent bug
    #    that never surfaced before v0.1.6 because the slurm pipeline was
    #    mono-only, so the FX burn input was always mono.  Once stereo
    #    became end-to-end (ADR-0021), the bug would have written corrupt
    #    files until this transpose was added.
    if was_mono:
        export = y[0]   # (1, n) → (n,)
    elif y.shape[0] == 1:
        # apply_fx may return shape (1, n) even when input was already 2-D
        # if all _fx_* stages treated it as mono.  Squeeze for consistency.
        export = y[0]
    else:
        export = y.T    # (channels, n) → (n, channels) for soundfile

    # 6. Write to a new session-scoped temp file.
    return _write_audio(export, sr, (out_fmt or "wav").lower())


def render_video(
    slurm_audio_path: str,
    fx_audio_path: str | None,
    audio_source_label: str,                # "slurm output" | "FX-burned output"
    title_text: str,
    creator_text: str,
    include_source_filename: bool,
    # Slurmify params (for metadata blob) ─────────────────────────────────────
    src_input_path: str,
    speed, resolution, transient_sensitivity, envelope_ms,
    preserve_pitch, pitch_shift_semitones,
    randomize_order, reverse_chance, stutter_chance,
    stutter_skip_ms, stutter_max_reps, stutter_spread,
    beat_trim_start_ms, beat_trim_end_ms, beat_gap_ms,
    bpm_override_text,
    seed_text,
    beat_mask_json,
    # Note-mode counterparts (ADR-0020) — added in v0.1.5 ────────────────────
    # Each (mode, note) pair captures whether a slider was in ms or ♪ mode
    # at render time and, if ♪, what note fraction the user picked.  These
    # land in the PATCH metadata so a re-imported MP4 can faithfully restore
    # both the value AND the unit the user was working with.
    stutter_skip_mode_val: str = "ms",   stutter_skip_note_val: str = "",
    beat_trim_start_mode_val: str = "ms", beat_trim_start_note_val: str = "",
    beat_trim_end_mode_val: str = "ms",   beat_trim_end_note_val: str = "",
    beat_gap_mode_val: str = "ms",        beat_gap_note_val: str = "",
    # FX params (for metadata blob) ────────────────────────────────────────────
    dist_drive=None, ring_freq=None, ring_depth=None,
    delay_time=None, delay_fb=None, delay_mix=None,
    phase_rate=None, phase_depth=None,
):
    """Render a YouTube-ready MP4 (1920×1080) from the slurm output.

    Returns the path to the rendered MP4 in the session temp directory.
    Audio is taken from either the raw slurm output or the FX-burned file,
    based on `audio_source_label`.

    The video stream is STREAM-COPIED from the pre-encoded loop animation at
    assets/siebaSlurm_A003.mp4 — no re-encoding of the video track happens at
    all.  ffmpeg only has to:
      1. Loop the pre-encoded H.264 video to match the audio duration.
      2. Encode the audio track to AAC 192 kbps @ 48 000 Hz (YouTube spec).
      3. Write a self-describing PATCH JSON blob into the MP4 metadata atoms
         so the file knows its own slurmify parameters (ADR-0008).

    The stream-copy approach makes render time proportional to audio-encode
    time alone, not video-encode time — roughly 100× faster than re-encoding
    from the source PNGs every run.

    Parameters
    ──────────
    slurm_audio_path : str
        Path to the dry slurmify output (always required, even if FX-burned
        output is selected — used as a fallback and validity check).
    fx_audio_path : str | None
        Path to the FX-burned output, or None if burn has never been run.
    audio_source_label : str
        Radio button value from the video panel: "slurm output" or
        "FX-burned output".  If "FX-burned output" is selected but no burn
        file exists, we auto-burn from the current FX slider values.
    title_text, creator_text : str
        Optional user-supplied strings embedded in the MP4 title/artist atoms.
    include_source_filename : bool
        If True, the source filename is included in the PATCH JSON.
        If False, the JSON is anonymous (no filename leakage).
    src_input_path : str
        Full path to the original uploaded file — used for the jumble suffix
        and optionally for the PATCH metadata if include_source_filename=True.
    seed_text : str
        The seed textbox value.  Parsed to int if non-empty and numeric.
    All other params match Gradio slider/checkbox names for the metadata blob.
    """
    # Validate the dry slurm output — required no matter what.
    if not slurm_audio_path or not os.path.exists(str(slurm_audio_path)):
        raise gr.Error("Run slurmify first — no audio to render.")

    # Pick the audio source.
    # If the user selected "FX-burned output" but has never clicked burn,
    # fx_audio_path will be None.  Rather than silently falling back to dry
    # audio (which would produce a confusing result), we auto-burn from the
    # current FX slider values.  The auto-burn uses a lossless WAV intermediate
    # because ffmpeg will re-encode it to AAC anyway.
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
                "wav",   # lossless intermediate; ffmpeg re-encodes to AAC anyway
            )
            print(f"[slurm] video: auto-burned FX → {audio_path}")
    else:
        audio_path = slurm_audio_path
        print(f"[slurm] video: using dry slurm audio → {audio_path}")

    # Resolve the pre-encoded loop animation file.
    # See the long comment in the module docstring and in app.py for the
    # ffmpeg one-liner to regenerate it from source PNGs if needed.
    loop_path = _asset("assets/siebaSlurm_A003.mp4")
    if not os.path.exists(loop_path):
        raise gr.Error(
            "Missing animation loop — assets/siebaSlurm_A003.mp4 not found."
        )

    # Parse the seed string (the textbox delivers strings, not ints).
    try:
        seed_int = int(seed_text) if seed_text and str(seed_text).strip() else None
    except (TypeError, ValueError):
        seed_int = None

    # Build the output filename: Subvoyant_Siena_Slurmify_<title>_<jumble>.mp4
    # The jumble suffix keeps filenames unique and gives each render a slurmy
    # character fingerprint derived from (and visually similar to) the source.
    safe_title = _safe_title(title_text or "")
    jumble = _jumble_name(src_input_path or "untitled", length=16, seed=seed_int)
    parts = ["Subvoyant_Siena_Slurmify"]
    if safe_title:
        parts.append(safe_title)
    parts.append(jumble)
    fname = "_".join(parts) + ".mp4"
    out_path = _new_temp_path(suffix=f"_{fname}", prefix="slurmvid_")

    # Build the PATCH JSON blob (ADR-0008) — the full slurmify parameter set
    # that produced this audio, embedded into the MP4 description atom.
    # YouTube will surface the description on upload; any future "import patch"
    # feature can extract it from the file.
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
            "beat_trim_start_ms":    float(beat_trim_start_ms) if beat_trim_start_ms is not None else 0.0,
            "beat_trim_end_ms":      float(beat_trim_end_ms) if beat_trim_end_ms is not None else 0.0,
            "beat_gap_ms":           float(beat_gap_ms) if beat_gap_ms is not None else 0.0,
            "bpm_override":          (float(bpm_override_text)
                                      if bpm_override_text and str(bpm_override_text).strip()
                                      else None),
            # beat_mask is stored as the raw JSON string (e.g. "[true,false,true,true]")
            # so the PATCH blob is round-trippable without losing fidelity.
            "beat_mask":             (beat_mask_json.strip()
                                      if beat_mask_json and str(beat_mask_json).strip()
                                      else None),
            # ── Note-mode unit selections (ADR-0020) ──────────────────────
            # These four (mode, note) pairs let a re-imported PATCH faithfully
            # restore which sliders were in ♪ mode at render time and what
            # note fractions they were set to.  Older PATCH blobs from v0.1.4
            # and earlier won't have these keys; the importer should treat
            # missing keys as ("ms", "") (full backward compatibility).
            "stutter_skip_mode":     str(stutter_skip_mode_val or "ms"),
            "stutter_skip_note":     str(stutter_skip_note_val or ""),
            "beat_trim_start_mode":  str(beat_trim_start_mode_val or "ms"),
            "beat_trim_start_note":  str(beat_trim_start_note_val or ""),
            "beat_trim_end_mode":    str(beat_trim_end_mode_val or "ms"),
            "beat_trim_end_note":    str(beat_trim_end_note_val or ""),
            "beat_gap_mode":         str(beat_gap_mode_val or "ms"),
            "beat_gap_note":         str(beat_gap_note_val or ""),
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

    title_for_meta   = (title_text   or "").strip() or f"Subvoyant Slurm {jumble}"
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

    # MP4 metadata atoms — YouTube reads title, artist, date, and description.
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

    # Locate ffmpeg — prefer the imageio-ffmpeg bundled binary (set in PATH
    # by app.py's bootstrap), fall back to whatever is on the system PATH.
    ffmpeg_exe = shutil.which("ffmpeg") or os.environ.get("FFMPEG_BINARY", "ffmpeg")

    # Build the ffmpeg command.
    # -stream_loop -1: repeat input 0 (the loop MP4) indefinitely.
    # -shortest:       stop when the shorter stream (the audio) ends.
    # -c:v copy:       stream-copy video — no re-encode, extremely fast.
    # -c:a aac:        encode audio to AAC 192 kbps @ 48 000 Hz for YouTube.
    # +faststart:      move the moov atom to the front so YouTube can seek
    #                  before the full file is downloaded.
    cmd = [
        ffmpeg_exe, "-y",
        # input 0: pre-encoded loop animation, looped to cover audio duration
        "-stream_loop", "-1", "-i", loop_path,
        # input 1: slurm (or FX-burned) audio
        "-i", str(audio_path),
        # route streams: video from input 0, audio from input 1
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
        # Surface the last few lines of ffmpeg stderr so the UI shows a useful
        # diagnostic rather than a generic "something went wrong" message.
        err = (e.stderr or b"").decode(errors="replace").splitlines()
        tail = "\n".join(err[-12:]) if err else "(no ffmpeg stderr)"
        raise gr.Error(f"Video render failed.\n{tail}")

    return out_path


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
    beat_trim_start_ms,
    beat_trim_end_ms,
    beat_gap_ms,
    bpm_override_text,
    output_format,
    start_sec,
    end_sec,
    seed_text,
    beat_mask_json: str = "",
    # ── Note-mode counterparts (ADR-0020) ───────────────────────────────────
    # Each of these matches a `_ms` parameter above.  The UI sends both;
    # whichever mode the user has selected for that slider is the one whose
    # value is "live".  We forward both into slurmify and pass a non-empty
    # note string ONLY if the slider is currently in "♪" mode.  That
    # decision is made below using the per-slider mode strings.
    stutter_skip_mode_val: str = "ms",
    stutter_skip_note_val: str = "",
    beat_trim_start_mode_val: str = "ms",
    beat_trim_start_note_val: str = "",
    beat_trim_end_mode_val: str = "ms",
    beat_trim_end_note_val: str = "",
    beat_gap_mode_val: str = "ms",
    beat_gap_note_val: str = "",
    progress=gr.Progress(),
):
    """Main Gradio event handler: slurmify the uploaded audio file.

    This is the Python function wired to the go_btn.click chain.  It:
      1. Validates the upload and extension.
      2. Parses the seed and BPM override text boxes.
      3. Loads the audio via slurmio.load_audio at 44 100 Hz, preserving
         source channels (mono → 1-D, stereo → (channels, n) — ADR-0021).
      4. Calls slurmcore.slurmify — pure DSP, no I/O.
      5. Transposes stereo output (channels, n) → (n, channels) for
         soundfile's expected layout.
      6. Writes the output via slurmio._write_audio.
      7. Returns the temp file path (Gradio wires it into audio_out).

    Stereo is end-to-end as of v0.1.6 (ADR-0021).  A mono source produces
    a mono output file; a stereo source produces a stereo output file.

    The gr.Progress() default argument lets Gradio inject a progress bar
    callback automatically — slurmify() receives it as `_progress` and
    calls it at each pipeline stage.
    """
    if audio_file is None:
        raise gr.Error("Drop in an audio file first.")

    ext = Path(audio_file).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise gr.Error(
            f"Unsupported format: {ext}. Try one of: {sorted(SUPPORTED_EXTS)}"
        )

    # Parse the seed — blank or non-numeric textbox value means "random".
    seed = None
    if seed_text and str(seed_text).strip():
        try:
            seed = int(seed_text)
        except ValueError:
            seed = None

    try:
        # Parse BPM override — accept blank or non-numeric as None (auto-detect).
        bpm_ov = None
        if bpm_override_text and str(bpm_override_text).strip():
            try:
                bpm_ov = float(bpm_override_text)
                if bpm_ov <= 0:
                    bpm_ov = None   # nonsensical value — treat as unset
            except (ValueError, TypeError):
                bpm_ov = None

        # Parse the bar mask JSON string sent from the browser chip strip.
        # The JS writes a value like "[true,false,true,true]" into the hidden
        # textbox.  We parse it here and pass it to slurmify().
        # An empty string, all-True, or malformed JSON all resolve to None,
        # which tells slurmify() to keep everything (default behaviour).
        beat_mask = None
        if beat_mask_json and str(beat_mask_json).strip():
            try:
                arr = json.loads(beat_mask_json)
                if isinstance(arr, list) and len(arr) > 0:
                    bools = [bool(x) for x in arr]
                    # All-True = no masking — treat same as None for efficiency.
                    if not all(bools):
                        beat_mask = bools
            except (json.JSONDecodeError, TypeError, ValueError):
                beat_mask = None   # malformed JSON from the browser → ignore

        # Resolve which note strings are "live" — only the ones whose mode
        # toggle is currently set to "♪" should reach slurmify().  This way
        # a slider that is in "ms" mode passes nothing for the note arg, and
        # slurmify falls through to the `_ms` value untouched (the long-
        # standing behaviour).  See ADR-0020.
        active_stutter_skip_note    = (stutter_skip_note_val
                                       if stutter_skip_mode_val == "♪" else "")
        active_trim_start_note      = (beat_trim_start_note_val
                                       if beat_trim_start_mode_val == "♪" else "")
        active_trim_end_note        = (beat_trim_end_note_val
                                       if beat_trim_end_mode_val == "♪" else "")
        active_beat_gap_note        = (beat_gap_note_val
                                       if beat_gap_mode_val == "♪" else "")

        # Load the audio into a numpy array.  slurmcore.slurmify is a pure DSP
        # function that takes arrays in and arrays out — it never touches the
        # filesystem.  All IO (load + write) happens here.
        y, sr = load_audio(audio_file)
        y_out, sr_out = slurmify(
            y=y,
            sr=sr,
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
            stutter_max_reps=int(stutter_max_reps if stutter_max_reps is not None else 0),
            stutter_spread=float(stutter_spread or 0),
            beat_trim_start_ms=float(beat_trim_start_ms or 0),
            beat_trim_end_ms=float(beat_trim_end_ms or 0),
            beat_gap_ms=float(beat_gap_ms or 0),
            bpm_override=bpm_ov,
            start_sec=float(start_sec or 0),
            end_sec=float(end_sec or 0),
            seed=seed,
            beat_mask=beat_mask,
            stutter_skip_note=active_stutter_skip_note,
            beat_trim_start_note=active_trim_start_note,
            beat_trim_end_note=active_trim_end_note,
            beat_gap_note=active_beat_gap_note,
            _progress=progress,
        )

        # ── Channel-layout boundary (ADR-0021) ──────────────────────────────
        # slurmify returns audio in slurmcore's channels-FIRST convention:
        #   shape (n,)              for mono
        #   shape (n_channels, n)   for stereo
        #
        # soundfile (used inside _write_audio) expects the OPPOSITE for
        # stereo:
        #   shape (n,)              for mono
        #   shape (n, n_channels)   for stereo
        #
        # Mono passes through unchanged in either convention.  For stereo
        # we transpose at this boundary so _write_audio gets the layout
        # it documents.  (This mirrors what burn_fx already does for the
        # FX-burn path.)
        if y_out.ndim == 2:
            y_out = y_out.T
        return _write_audio(y_out, sr_out, output_format)
    except ValueError as e:
        # slurmify raises ValueError for user-facing error conditions
        # (e.g., trim range invalid, audio too short).  Wrap in gr.Error so
        # Gradio displays a friendly red banner rather than a raw traceback.
        raise gr.Error(str(e))


def _quit_app():
    """Shut down the Gradio server process cleanly from the browser UI.

    A short timer (0.8 s) lets Gradio flush its HTTP response before
    os._exit fires, so the user sees the confirmation toast in the browser
    rather than a sudden connection error.  os._exit(0) is used (not
    sys.exit) because sys.exit only raises SystemExit, which Gradio's ASGI
    server catches and ignores — os._exit bypasses all that.
    """
    threading.Timer(0.8, lambda: os._exit(0)).start()
    return gr.Info("Shutting down — you can close this tab.")


# ─────────────────────────────────────────────────────────────────────────────
# Gradio layout
# ─────────────────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    """Construct and return the complete Gradio Blocks layout.

    Called once by app.py's __main__ block.  The returned `demo` object is
    passed directly to demo.launch().

    Structure
    ─────────
      • Header (logo + skin picker)
      • Upload zone (gr.File → audio_in routing)
      • In/Out trim bar + utility bar (randomize, reveal temp)
      • Slurm parameters (left column: speed, resolution, trim, transient,
        envelope; right column: pitch, stutter, seed, format, go button)
      • Loading dancer (hidden unless processing)
      • Audio output + VU meter
      • FX accordion (distortion, ring mod, delay, phaser, FX preview, burn)
      • Video export accordion

    Theme and CSS are NOT set here — they're passed to launch() in app.py
    because Gradio 6 requires them at launch time, not at layout-build time.
    """
    # theme and CSS are set in launch() in app.py (Gradio 6 requirement)
    with gr.Blocks(title="Subvoyant SIENA Slurmer") as demo:

        # ── Header: logo + app name + version + skin picker ──────────────────
        # _ICON_TAG is the pre-assembled <a><img> HTML from ui_assets.py.
        # The version in the slurm-tag div must match __version__ above.
        gr.HTML(
            """
            <div class="slurm-header">
              """ + _ICON_TAG + """
              <div class="slurm-header-text">
                <h1 class="slurm-title"><a href="https://www.subvoyant.com" target="_blank" rel="noopener noreferrer" class="slurm-header-link">SIENA SLURMER</a></h1>
                <div class="slurm-tag">subvoyant · chopped · sped-up · transient-sliced · v0.1.6</div>
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
                # ── Universal upload — accepts ANY audio or video file ─────────
                # gr.Audio's MIME validation rejects video/* uploads server-side
                # regardless of what the browser file picker shows.  To make
                # "drop any file" actually work, the primary upload is a
                # gr.File (no MIME filtering); the _route_upload handler below
                # routes audio files through directly and runs ffmpeg on video
                # files to extract their audio track.  The result populates
                # audio_in below — which only becomes visible AFTER a file is
                # loaded, so there's no chance of dropping on the wrong target.
                # See ADR-0009 for the full explanation.
                media_file_in = gr.File(
                    label="🎵📹 drop ANY audio or video file here",
                    file_count="single",
                    type="filepath",
                    file_types=None,   # accept anything — MIME filtering is done in Python
                    elem_id="slurm-media-file",
                    elem_classes=["slurm-media-file"],
                )

                audio_in = gr.Audio(
                    label="input audio",
                    type="filepath",
                    sources=["upload"],
                    elem_classes=["slurm-audio"],
                    visible=False,   # hidden until _route_upload populates it
                )

                # ── In/Out trim bar ───────────────────────────────────────────
                # Real Gradio buttons + fn=None,js= is the only reliable
                # way to read audio.currentTime into Gradio state in Gradio 5+.
                # Scripts inside gr.HTML use innerHTML injection and are silently
                # ignored by modern browsers (DOM security policy).
                # The clock display and keyboard shortcuts live in INIT_JS.
                with gr.Row(elem_id="slurm-inout-bar"):
                    gr.HTML('<div id="slurm-clock-wrap">► 0:00.00</div>')
                    in_btn    = gr.Button("[ I ] in",  elem_id="slurm-in-btn",
                                          elem_classes=["slurm-io-btn"], size="sm")
                    out_btn   = gr.Button("[ O ] out", elem_id="slurm-out-btn",
                                          elem_classes=["slurm-io-btn"], size="sm")
                    clear_btn = gr.Button("✕ clear",   elem_id="slurm-clear-btn",
                                          elem_classes=["slurm-io-btn", "slurm-io-clear"], size="sm")

                # ── Utility bar: randomize all + reveal temp files ────────────
                # The randomize button gets the Hoberman-Max hover gif
                # (slurm-max-popup class) — the same "Max-the-tester chaos"
                # Easter egg treatment as MAX RANDOM.
                # Reveal opens SESSION_TMP_DIR in the OS file browser so users
                # can find and save output files before the session ends and the
                # directory gets wiped.
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
                        info="0 = from start",
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

                # ── Beat mask container (populated by _slurmBuildBeatMask in JS) ──
                # A plain HTML div that INIT_JS writes chip buttons into whenever
                # the resolution changes.  This keeps the Gradio layout static
                # while the chip contents are dynamic.
                gr.HTML('<div id="slurm-beat-mask"></div>')

                # Hidden textbox that carries the current beat-mask boolean array
                # from the browser to Python.  At Go-button-click time a JS-only
                # first step reads window._slurmBeatMask and returns it through
                # Gradio's own output path into this textbox.  process() reads
                # and parses the JSON string (e.g. "[true,false,true,true]").
                # It is intentionally invisible — the chip strip above is the UI.
                beat_mask_val = gr.Textbox(
                    value="",
                    visible=False,
                    elem_id="slurm-beat-mask-val",
                    max_lines=1,
                )

                # Beat trim controls — sit directly below the chip strip,
                # split 50/50 across the same column width.  These trim the
                # raw slice from the start and/or end before the envelope is
                # applied, so the fade lands at the new cut boundaries.
                #
                # Each trim control is a tuple of three Gradio components
                # plus an HTML hint span — see ADR-0020:
                #   • the original ms slider (visible by default)
                #   • a note-fraction dropdown (visible only in ♪ mode)
                #   • a mode toggle radio (ms ⇄ ♪)
                #   • a hint <span> that JS keeps in sync with the active
                #     value at the active BPM ("≈ 31 ms @ 120 BPM")
                # Each component has a stable elem_id so INIT_JS can locate
                # them by data-attribute when wiring up the live hint.
                with gr.Row():
                    with gr.Column():
                        beat_trim_start = gr.Slider(
                            label="trim start (ms)",
                            minimum=0.0, maximum=500.0, step=5.0, value=0.0,
                            info="remove N ms from the start of every beat · 0 = off",
                            elem_id="slurm-trim-start-ms",
                        )
                        beat_trim_start_note = gr.Dropdown(
                            label="trim start (♪)",
                            choices=_NOTE_CHOICES, value=_NOTE_DEFAULT,
                            visible=False,
                            elem_id="slurm-trim-start-note",
                            elem_classes=["slurm-dropdown", "slurm-note-dropdown"],
                        )
                        beat_trim_start_mode = gr.Radio(
                            choices=_UNIT_MODE_CHOICES, value="ms",
                            show_label=False, container=False,
                            elem_id="slurm-trim-start-mode",
                            elem_classes=["slurm-unit-toggle"],
                        )
                        gr.HTML(
                            '<div class="slurm-unit-hint" '
                            'id="slurm-unit-hint-trim-start" '
                            'data-target="trim_start"></div>'
                        )
                    with gr.Column():
                        beat_trim_end = gr.Slider(
                            label="trim end (ms)",
                            minimum=0.0, maximum=500.0, step=5.0, value=0.0,
                            info="remove N ms from the end of every beat · 0 = off",
                            elem_id="slurm-trim-end-ms",
                        )
                        beat_trim_end_note = gr.Dropdown(
                            label="trim end (♪)",
                            choices=_NOTE_CHOICES, value=_NOTE_DEFAULT,
                            visible=False,
                            elem_id="slurm-trim-end-note",
                            elem_classes=["slurm-dropdown", "slurm-note-dropdown"],
                        )
                        beat_trim_end_mode = gr.Radio(
                            choices=_UNIT_MODE_CHOICES, value="ms",
                            show_label=False, container=False,
                            elem_id="slurm-trim-end-mode",
                            elem_classes=["slurm-unit-toggle"],
                        )
                        gr.HTML(
                            '<div class="slurm-unit-hint" '
                            'id="slurm-unit-hint-trim-end" '
                            'data-target="trim_end"></div>'
                        )

                # Beat gap — full-width below the trim row.
                beat_gap = gr.Slider(
                    label="beat gap (ms)",
                    minimum=0.0, maximum=3600.0, step=10.0, value=0.0,
                    info="silence inserted between every beat · 0 = off · short = staccato · long = sparse/isolated",
                    elem_id="slurm-beat-gap-ms",
                )
                beat_gap_note = gr.Dropdown(
                    label="beat gap (♪)",
                    choices=_NOTE_CHOICES, value=_NOTE_DEFAULT,
                    visible=False,
                    elem_id="slurm-beat-gap-note",
                    elem_classes=["slurm-dropdown", "slurm-note-dropdown"],
                )
                beat_gap_mode = gr.Radio(
                    choices=_UNIT_MODE_CHOICES, value="ms",
                    show_label=False, container=False,
                    elem_id="slurm-beat-gap-mode",
                    elem_classes=["slurm-unit-toggle"],
                )
                gr.HTML(
                    '<div class="slurm-unit-hint" '
                    'id="slurm-unit-hint-beat-gap" '
                    'data-target="beat_gap"></div>'
                )

                bpm_override = gr.Textbox(
                    label="BPM override (optional)",
                    placeholder="leave blank for auto-detect",
                    info="set if the tempo sounds off — e.g. enter 140 if librosa detected 70 · also drives the ♪→ms conversion shown next to musical sliders",
                    elem_id="slurm-bpm-override",   # JS unit-hint reader targets this
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
                    minimum=0.0, maximum=1.0, step=0.05, value=0.0,
                    info="probability each slice is stuttered",
                )
                stutter_skip_ms = gr.Slider(
                    label="skip length (ms)",
                    minimum=0.0, maximum=500.0, step=5.0, value=0.0,
                    info="0 = full-slice repeat (classic) · 5–15 ms = glitch buzz · 20–50 ms = CD-skip · 100–500 ms = phrase loop",
                    elem_id="slurm-stutter-skip-ms",
                )
                # Note-mode counterpart for stutter skip length (ADR-0020).
                # Hidden by default; the unit toggle below swaps visibility.
                # Default to a small note (1/32) since stutter is most musical
                # at glitch-scale durations rather than long held-note loops.
                stutter_skip_note = gr.Dropdown(
                    label="skip length (♪)",
                    choices=_NOTE_CHOICES, value="1/32",
                    visible=False,
                    elem_id="slurm-stutter-skip-note",
                    elem_classes=["slurm-dropdown", "slurm-note-dropdown"],
                )
                stutter_skip_mode = gr.Radio(
                    choices=_UNIT_MODE_CHOICES, value="ms",
                    show_label=False, container=False,
                    elem_id="slurm-stutter-skip-mode",
                    elem_classes=["slurm-unit-toggle"],
                )
                gr.HTML(
                    '<div class="slurm-unit-hint" '
                    'id="slurm-unit-hint-stutter-skip" '
                    'data-target="stutter_skip"></div>'
                )
                stutter_max_reps = gr.Slider(
                    label="reps (max)",
                    minimum=0, maximum=16, step=1, value=0,
                    info="upper bound for repeat count — draw is random 2 → max · 0 = stutter off",
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
                # Acid skin reads and positions this absolute halo div behind go_btn.
                gr.HTML('<div id="slurm-go-halo"></div>')
                quit_btn = gr.Button("⏻ quit app", variant="stop", size="sm")

        # ── Loading dancer ────────────────────────────────────────────────────
        # The Siena dancer GIF is hidden at page load and made visible while
        # the slurmify pipeline is running.  go_btn.click shows it; the
        # .then() chain hides it again when process() returns.
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

        # VU meter canvas — visible only in the hardware skin (CSS-gated by
        # body[data-skin="hardware"]).  INIT_JS taps the FX chain's AnalyserNode
        # and draws RMS bar readings here in real time.
        gr.HTML('<canvas id="slurm-vu-meter" width="800" height="28"></canvas>')

        # ── Mirror audio_out URL into the FX preview element ─────────────────
        # When audio_out changes, pipe the file URL into #slurm-fx-audio so the
        # Web Audio FX chain can play the output through the live effect rack.
        # fn=None + js= runs entirely on the frontend (no Python round-trip).
        # Gradio passes the audio FileData object, which carries a frontend-
        # resolvable .url for the served file — we don't have to scrape
        # Gradio's WaveSurfer shadow DOM to find the audio URL.
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

        # ── Auto-check shuffle when MAX RANDOM is selected ────────────────────
        # Without shuffle, MAX RANDOM only randomizes slice POSITIONS but the
        # slices still play in original order — sounds like "song with random
        # fades" rather than genuine chaos.  Auto-checking the shuffle box
        # surfaces this expected behaviour in the UI; the user can override by
        # manually unchecking it.  See ADR-0013 for the rationale behind keeping
        # this as a UI reaction rather than internalising it inside slurmify().
        def _on_resolution_change(res):
            if res == "MAX RANDOM":
                return gr.update(value=True)   # auto-check shuffle
            return gr.update()                 # any other mode: leave checkbox alone

        # Handler 1 (Python): update the shuffle checkbox when resolution changes.
        resolution.change(
            fn=_on_resolution_change,
            inputs=resolution,
            outputs=randomize_order,
        )

        # Handler 2 (JS-only, standalone): rebuild the beat-mask chip strip.
        # This is a SEPARATE .change() call — not a .then() chain — because
        # fn=None with outputs=[] in a chained .then() step stops firing after
        # any preceding Python round-trip (like a slurmify run) completes.
        # A standalone fn=None handler with a real output is the reliable pattern
        # (same as in_btn / out_btn; see CLAUDE.md §"Python ↔ JavaScript boundary").
        # The JS rebuilds the chip strip for the new resolution, then returns ""
        # to beat_mask_val — correctly resetting the mask to all-on whenever the
        # resolution changes (same reset that _slurmBuildBeatMask does internally).
        resolution.change(
            fn=None,
            inputs=[resolution],
            outputs=[beat_mask_val],
            js="(v) => { window.slurmBuildBeatMask && window.slurmBuildBeatMask(v); return ['']; }",
        )

        # ── Unit-mode toggle handlers (ADR-0020) ──────────────────────────────
        # Each of the four musical sliders has a paired (slider, dropdown,
        # mode_radio) trio.  The mode radio's `.change` event drives a
        # visibility swap between the slider and the dropdown via
        # _swap_unit_mode().  Visibility updates apply instantly; no full
        # rerender.
        #
        # localStorage persistence of the user's chosen mode is handled
        # entirely client-side in INIT_JS — see _slurmInitUnitToggles in
        # ui_assets.py.  This Python handler is concerned only with the
        # "mode changed → swap visibility" reaction.
        stutter_skip_mode.change(
            fn=_swap_unit_mode,
            inputs=stutter_skip_mode,
            outputs=[stutter_skip_ms, stutter_skip_note],
        )
        beat_trim_start_mode.change(
            fn=_swap_unit_mode,
            inputs=beat_trim_start_mode,
            outputs=[beat_trim_start, beat_trim_start_note],
        )
        beat_trim_end_mode.change(
            fn=_swap_unit_mode,
            inputs=beat_trim_end_mode,
            outputs=[beat_trim_end, beat_trim_end_note],
        )
        beat_gap_mode.change(
            fn=_swap_unit_mode,
            inputs=beat_gap_mode,
            outputs=[beat_gap, beat_gap_note],
        )

        # ── Randomize all slurm parameters ────────────────────────────────────
        # Scrambles every parameter EXCEPT input audio, in/out trim points,
        # output format, and seed — those are intentional user choices that
        # "randomize all" shouldn't blow away.
        # Ranges are biased toward musical-sounding values rather than full
        # extremes — e.g. speed in 0.5–3.0 rather than 0.05–4.0, and pitch
        # shift weighted toward octaves and 5ths rather than uniform semitones.
        def _randomize_all():
            _RES_CHOICES = ["1/1", "1/2", "1/4", "1/8", "1/16",
                            "1/32", "1/64", "1/128", "MAX RANDOM"]
            new_res = random.choice(_RES_CHOICES)
            print(f"[slurm] randomize all → resolution={new_res}")
            return {
                speed:                 round(random.uniform(0.5, 3.0), 2),
                resolution:            new_res,
                transient_sensitivity: round(random.random(), 2),
                envelope_ms:           round(random.uniform(0.0, 8.0), 1),
                preserve_pitch:        random.random() < 0.7,  # bias toward preserve
                # Weighted toward musically-meaningful intervals (octaves, 5ths)
                pitch_shift_semitones: random.choice(
                    [-12, -7, -5, -3, 0, 0, 0, 3, 5, 7, 12]),
                randomize_order:       (new_res == "MAX RANDOM") or (random.random() < 0.5),
                reverse_chance:        round(random.uniform(0.0, 0.5), 2),
                stutter_chance:        round(random.uniform(0.0, 0.5), 2),
                # Stutter engine — bias toward interesting ranges:
                # skip_ms weighted toward 0 (classic) and the skippy 15–40 ms zone
                stutter_skip_ms:       float(random.choice(
                    [0, 0, 0, 10, 15, 20, 25, 30, 40, 50])),
                stutter_max_reps:      int(random.choice([2, 3, 4, 4, 6, 8])),
                stutter_spread:        round(random.uniform(0.0, 0.6), 2),
                # Note-mode counterpart for stutter skip (ADR-0020).
                # Only the dropdown is randomized; the mode radio is left alone
                # so the user keeps whichever unit they were working in.  When
                # in ms mode this update is invisible but harmless; when in ♪
                # mode the user sees their dropdown reroll along with the rest.
                # Bias toward short notes — that's where stutter is most musical.
                stutter_skip_note:     random.choice(
                    ["1/64", "1/32", "1/32", "1/16T", "1/16", "1/16", "1/16."]),
            }

        randomize_all_btn.click(
            fn=_randomize_all,
            inputs=[],
            outputs=[speed, resolution, transient_sensitivity, envelope_ms,
                     preserve_pitch, pitch_shift_semitones, randomize_order,
                     reverse_chance, stutter_chance,
                     stutter_skip_ms, stutter_max_reps, stutter_spread,
                     stutter_skip_note],
        )

        # ── Reveal temp files in OS file browser ──────────────────────────────
        reveal_tmp_btn.click(fn=_reveal_temp_dir, inputs=[], outputs=[])

        # ── Universal upload router → audio_in ────────────────────────────────
        # The single drop zone (media_file_in) accepts ANY file extension.
        # This handler routes by file extension:
        #   • Audio extension (in _AUDIO_EXTS) → pass the path straight through
        #     to audio_in so the waveform + transport render immediately.
        #   • Video / other media → invoke ffmpeg -vn to strip the video stream
        #     and extract the audio as a 16-bit 44 100 Hz stereo WAV.
        # In both cases, audio_in is made VISIBLE so the waveform renders.
        # audio_in starts with visible=False so the page doesn't show an empty
        # audio component before any file is loaded.
        def _route_upload(media_path):
            if not media_path:
                # File was cleared — hide audio_in again.
                return gr.update(value=None, visible=False)

            src = (media_path if isinstance(media_path, str)
                   else getattr(media_path, "name", str(media_path)))
            ext = Path(src).suffix.lower()

            if ext in _AUDIO_EXTS:
                # Audio file — pass the path straight through.
                print(f"[slurm] audio file uploaded: {src}")
                return gr.update(value=src, visible=True)

            # Non-audio (video / container) — extract the audio track via ffmpeg.
            print(f"[slurm] non-audio file uploaded — ffmpeg extracting: {src}")
            out_path = _new_temp_path(suffix=".wav", prefix="extracted_")
            ffmpeg_exe = (shutil.which("ffmpeg")
                          or os.environ.get("FFMPEG_BINARY", "ffmpeg"))
            try:
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", src,
                     "-vn",                       # drop the video stream
                     "-acodec", "pcm_s16le",      # 16-bit PCM WAV
                     "-ar", "44100",              # match TARGET_SR so load_audio is happy
                     "-ac", "2",                  # stereo (load_audio mono-mixes later)
                     out_path],
                    check=True, capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                err_tail = (e.stderr or b"").decode("utf-8", errors="replace")[-500:]
                print(f"[slurm] ffmpeg extraction failed: {err_tail}")
                raise gr.Error(
                    f"Couldn't extract audio from that file. "
                    f"ffmpeg said: {err_tail[:200]}"
                )
            print(f"[slurm] extracted → {out_path}")
            return gr.update(value=out_path, visible=True)

        media_file_in.change(
            fn=_route_upload,
            inputs=media_file_in,
            outputs=audio_in,
        )

        # ── Go button: show dancer + capture beat mask → slurmify → hide dancer
        # Three-step .then() chain:
        #   1. Show dancer AND capture beat mask in a single Python call.
        #      This uses Gradio's "JS preprocessor" pattern: when both fn= and
        #      js= are provided on the same event handler, Gradio runs js= first
        #      client-side and its return value becomes the inputs for fn= (instead
        #      of the component values).  The JS reads window._slurmBeatMask (the
        #      boolean array maintained by the chip-strip code in INIT_JS) and
        #      returns it as a JSON string.  The Python lambda receives that string,
        #      stores it into beat_mask_val, and simultaneously makes the dancer
        #      visible.  This is the only reliable way to bridge JS state into
        #      Python in Gradio 5's Svelte runtime:
        #        - fn=None + outputs in a .then() step hangs (server never acks)
        #        - fn=None as the first .click() step silently breaks the chain
        #        - Writing to a <textarea> with the React native-setter trick does
        #          not update Svelte's internal state (always delivers "" to Python)
        #   2. Run process() — reads beat_mask_val (now populated by step 1).
        #   3. Hide the dancer when done.
        go_btn.click(
            # js= runs client-side first; its return value becomes fn= inputs.
            # Receives: beat_mask_val's current value (ignored by the JS).
            # Returns:  [JSON string of window._slurmBeatMask, or "[]" if unset].
            # Python fn: makes dancer visible and passes mask JSON through to output.
            fn=lambda mask_json: (gr.Image(visible=True), mask_json),
            inputs=[beat_mask_val],
            outputs=[dancer, beat_mask_val],
            js="(m) => [JSON.stringify(window._slurmBeatMask || [])]",
        ).then(
            fn=process,
            inputs=[
                audio_in, speed, resolution, transient_sensitivity,
                envelope_ms, preserve_pitch, pitch_shift_semitones,
                randomize_order, reverse_chance, stutter_chance,
                stutter_skip_ms, stutter_max_reps, stutter_spread,
                beat_trim_start, beat_trim_end, beat_gap,
                bpm_override,
                output_format, start_sec, end_sec, seed_text,
                beat_mask_val,
                # ── Note-mode plumbing (ADR-0020) ──────────────────────────
                # Order MUST match process()'s signature.  Each pair is
                # (mode_val, note_val) and they correspond to the four
                # musical sliders above in the same order.
                stutter_skip_mode, stutter_skip_note,
                beat_trim_start_mode, beat_trim_start_note,
                beat_trim_end_mode, beat_trim_end_note,
                beat_gap_mode, beat_gap_note,
            ],
            outputs=audio_out,
        ).then(
            fn=lambda: gr.Image(visible=False),
            inputs=[],
            outputs=dancer,
        )

        # ── In/Out button handlers ─────────────────────────────────────────────
        # fn=None + js= runs pure client-side JS with no Python round-trip.
        # The js= string MUST be a single callable function expression —
        # Gradio calls it and uses the return value to update the output.
        # Concatenating a bare declaration + an arrow function is NOT valid:
        # the frontend sees two statements, not one callable, and the page
        # freezes on "Loading…".
        #
        # WaveSurfer v7 embeds its <audio> element inside a shadow DOM, so
        # document.querySelector('audio') always misses it.  _probe_fn walks
        # every shadow root to find the <audio> with the highest currentTime,
        # then falls back to the on-screen timestamp text, then to any plain
        # <audio> in the document.
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
        out_btn.click(fn=None, inputs=[], outputs=[end_sec],   js=_probe_fn)
        clear_btn.click(fn=None, inputs=[], outputs=[start_sec, end_sec], js=_clear_js)

        quit_btn.click(fn=_quit_app, inputs=[], outputs=[])

        # ── FX Panel ──────────────────────────────────────────────────────────
        # Real-time effects via the Web Audio API — zero Python round-trip for
        # parameter changes.  The FX sliders fire window.slurmFx.set*() directly
        # via fn=None,js= wiring.  "Burn FX" bakes the current slider values
        # into a new audio file via the Python DSP path (burn_fx → apply_fx).
        with gr.Accordion("⚡ real-time FX", open=False,
                           elem_id="slurm-fx-panel"):

            with gr.Row():
                # ── Left column: Distortion + Ring Modulation ─────────────────
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

                # ── Right column: Delay + Phaser ──────────────────────────────
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

            # ── Live FX preview ───────────────────────────────────────────────
            # Dedicated <audio> element owned exclusively by the FX chain.
            # INIT_JS mirrors Gradio's output URL into this element and then
            # routes the signal through the Web Audio graph.
            # createMediaElementSource is bound to this element EXACTLY ONCE
            # for the lifetime of the page — see ADR-0003 for why rebinding
            # to the same element or to Gradio's WaveSurfer element would
            # break the AudioContext.
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

        # ── FX slider → Web Audio (no Python round-trip) ──────────────────────
        # Each slider fires the matching slurmFx setter on the Web Audio graph
        # via a tiny fn=None,js= handler.  The lambda builds the JS string;
        # `_js(fn)` returns a function expression that calls window.slurmFx.fn(v).
        _js = lambda fn: f"(v) => {{ window.slurmFx && window.slurmFx.{fn}(v); }}"
        fx_dist.change(fn=None,       inputs=[fx_dist],       outputs=[], js=_js("setDist"))
        fx_ring_freq.change(fn=None,  inputs=[fx_ring_freq],  outputs=[], js=_js("setRingFreq"))
        fx_ring_depth.change(fn=None, inputs=[fx_ring_depth], outputs=[], js=_js("setRingDepth"))
        fx_delay_time.change(fn=None, inputs=[fx_delay_time], outputs=[], js=_js("setDelayTime"))
        fx_delay_fb.change(fn=None,   inputs=[fx_delay_fb],   outputs=[], js=_js("setDelayFb"))
        fx_delay_mix.change(fn=None,  inputs=[fx_delay_mix],  outputs=[], js=_js("setDelayMix"))
        fx_phase_rate.change(fn=None, inputs=[fx_phase_rate], outputs=[], js=_js("setPhaseRate"))
        fx_phase_depth.change(fn=None,inputs=[fx_phase_depth],outputs=[], js=_js("setPhaseDepth"))

        # ── Burn FX: bake current FX settings into a new file ─────────────────
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

        # ── Video export panel ─────────────────────────────────────────────────
        # Looping Siena dancer animation + slurm audio, rendered to a
        # YouTube-ready 1920×1080 MP4 with the slurmify patch parameters
        # embedded in the MP4 metadata atoms (ADR-0008).
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
                # slurmify params for the PATCH metadata blob
                audio_in,
                speed, resolution, transient_sensitivity, envelope_ms,
                preserve_pitch, pitch_shift_semitones,
                randomize_order, reverse_chance, stutter_chance,
                stutter_skip_ms, stutter_max_reps, stutter_spread,
                beat_trim_start, beat_trim_end, beat_gap,
                bpm_override,
                seed_text,
                beat_mask_val,
                # ── Note-mode (mode, note) pairs (ADR-0020) ──────────────
                # Order MUST match render_video()'s signature so the metadata
                # blob captures which sliders were in ♪ mode at export time.
                stutter_skip_mode, stutter_skip_note,
                beat_trim_start_mode, beat_trim_start_note,
                beat_trim_end_mode, beat_trim_end_note,
                beat_gap_mode, beat_gap_note,
                # FX params for the PATCH metadata blob
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
