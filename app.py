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

# ── Filesystem IO layer — now lives in slurmio.py ───────────────────────────
# _asset, SESSION_TMP_DIR, _new_temp_path, _reveal_temp_dir,
# SUPPORTED_EXTS, TARGET_SR, load_audio, and _write_audio are all
# defined in slurmio.py (Phase 3 of the modularisation — ADR-0017).
#
# PYINSTALLER: "slurmio" must stay in hiddenimports in slurmify.spec or
# the bundled .app will crash on startup with ModuleNotFoundError.
from slurmio import (
    _asset,             # resolve bundled asset paths (dev vs. bundle)
    SESSION_TMP_DIR,    # per-session temp dir (auto-wiped on exit)
    _new_temp_path,     # create a session-scoped temp file
    _reveal_temp_dir,   # open SESSION_TMP_DIR in the OS file browser
    SUPPORTED_EXTS,     # set of accepted audio/video file extensions
    TARGET_SR,          # 44 100 Hz standard output sample rate
    load_audio,         # load any audio/video file → (ndarray, sr)
    _write_audio,       # write audio ndarray → session-scoped temp file
)


import gradio as gr
import librosa
import numpy as np
import pyrubberband as pyrb
import soundfile as sf

# ── Audio constants and load_audio — now live in slurmio.py ─────────────────
# SUPPORTED_EXTS, TARGET_SR, and load_audio have been extracted to
# slurmio.py (Phase 3 of the modularisation — ADR-0017).
# They are imported above with the rest of the slurmio names.

# ── DSP engine — now lives in slurmcore.py ───────────────────────────────────
# detect_slice_points, apply_envelope, and slurmify have been extracted to
# slurmcore.py (Phase 2 of the modularisation — ADR-0016).  That module is
# pure DSP: numpy arrays in, numpy arrays out, no file I/O, no Gradio.
#
# apply_fx (the pure DSP portion of burn_fx) is also in slurmcore.py.
#
# Import contract:
#   slurmify(y, sr, ...)     → (np.ndarray, int)   [refactored from str return]
#   apply_fx(y, sr, ...)     → (np.ndarray, int)   [new — was inside burn_fx]
#   detect_slice_points(...)  → np.ndarray           [unchanged interface]
#   apply_envelope(...)       → np.ndarray           [unchanged interface]
#   _fx_* helpers            — imported for render_video() and any future use
#
# PYINSTALLER: "slurmcore" must stay in hiddenimports in slurmify.spec.
# Local modules are not auto-detected by PyInstaller's static analysis.
from slurmcore import (
    detect_slice_points,    # beat-grid + transient-snap slice-point detection
    apply_envelope,         # per-slice fade-in/out (anti-click envelope)
    slurmify,               # main DSP pipeline: stretch → slice → FX → concat
    _fx_distortion,         # tanh waveshaper (DSP only — called by apply_fx)
    _fx_ring_mod,           # amplitude modulation via carrier oscillator
    _fx_delay,              # tape delay with feedback loop
    _fx_phaser,             # 4-stage allpass phaser with LFO
    apply_fx,               # full FX chain: distortion→ring→delay→phaser
)



# ── Output format helpers — now live in slurmio.py ──────────────────────────
# _SF_FORMATS, _FFMPEG_FORMATS, and _write_audio have been extracted to
# slurmio.py (Phase 3 of the modularisation — ADR-0017).
# They are imported above with the rest of the slurmio names.


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





# ── Audio Effects DSP — now lives in slurmcore.py ───────────────────────────
# _fx_distortion, _fx_ring_mod, _fx_delay, _fx_phaser, and apply_fx are all
# defined in slurmcore.py (Phase 2 of the modularisation — ADR-0016).
# They are imported below with the rest of the slurmcore names.
# burn_fx() (just below) is the thin Gradio wrapper that loads/writes files
# and delegates the pure DSP work to apply_fx().



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

    Flow:
      1. Validate the input path (raise gr.Error if missing — Gradio surfaces
         this as a friendly red banner rather than a raw Python traceback).
      2. Load the audio with librosa, preserving the original sample rate and
         channel layout (sr=None → keep native SR; mono=False → keep stereo).
      3. Ensure the array is 2-D (channels × samples) — the _fx_* functions in
         slurmcore.py expect that shape and handle mono/stereo themselves.
      4. Call apply_fx() from slurmcore — pure DSP, no I/O.
      5. Squeeze back to 1-D if the input was originally mono, so soundfile
         writes a proper mono file rather than a 1-channel stereo file.
      6. Write the result to a new temp file via _write_audio().

    Parameters match the Gradio slider names exactly (burn_btn.click wiring).
    """
    # 1. Guard: nothing to apply FX to yet.
    if not audio_path or not os.path.exists(str(audio_path)):
        raise gr.Error("Run slurmify first — no output to apply FX to.")

    # 2. Load — preserve native sample rate and channel count.
    #    librosa returns mono 1-D or stereo 2-D depending on the file.
    y, sr = librosa.load(audio_path, sr=None, mono=False)

    # 3. Promote to 2-D so apply_fx can handle mono and stereo uniformly.
    #    The _fx_* functions return 2-D; we'll squeeze back at step 5.
    was_mono = y.ndim == 1
    if was_mono:
        y = y[np.newaxis, :]
    y = y.astype(np.float32)

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

    # 5. Squeeze back to 1-D for mono, leave stereo as-is.
    #    soundfile expects (n,) for mono or (n, channels) for stereo.
    if was_mono:
        export = y[0]
    elif y.shape[0] == 1:
        # apply_fx may return shape (1, n) even when input was already 2-D
        # if all _fx_* stages treated it as mono.  Squeeze for consistency.
        export = y[0]
    else:
        export = y

    # 6. Write to a new session-scoped temp file.
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

        # Load the audio into a numpy array.  slurmcore.slurmify is now a
        # pure DSP function that takes arrays in and arrays out — it never
        # touches the filesystem.  IO (load + write) happens here in app.py.
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
            stutter_max_reps=int(stutter_max_reps or 4),
            stutter_spread=float(stutter_spread or 0),
            bpm_override=bpm_ov,
            start_sec=float(start_sec or 0),
            end_sec=float(end_sec or 0),
            seed=seed,
            _progress=progress,
        )
        return _write_audio(y_out, sr_out, output_format)
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
