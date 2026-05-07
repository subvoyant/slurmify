"""
Slurmify — bootstrap and application entry point.

After Phase 4 of the modularisation (ADR-0018), this file is deliberately
small — about 90 lines of code.  Its only responsibilities are:

  1. Wire up PyInstaller's frozen bundle path before any library import.
  2. Wire up imageio-ffmpeg's static binary so librosa/audioread can decode
     mp3/aac/m4a without a system ffmpeg install.
  3. Import the four modules that do all the real work.
  4. Run build_ui() and launch the Gradio server.

Where the real work lives
─────────────────────────
  slurm_ui.py  — all Gradio UI: layout, event handlers, video export, process()
  slurmcore.py — pure audio DSP: detect_slice_points, slurmify, apply_fx, _fx_*
  slurmio.py   — filesystem IO: load_audio, _write_audio, session-temp directory
  ui_assets.py — static browser content: INIT_JS, CUSTOM_CSS, base64 GIF/PNG

Run:  python app.py
Then open the URL it prints (usually http://127.0.0.1:7860).
"""

from __future__ import annotations

# Only stdlib modules needed for bootstrap and __main__ live here.
# Everything else is in the four modules above.
import os
import sys
import base64

# ---------------------------------------------------------------------------
# PyInstaller bundle bootstrap
# Must run before any library import that touches native binaries.
# The bootstrap block:
#   1. Prepends our vendored bin/ directory (rubberband binary) to PATH.
#   2. Disables numba JIT — it cannot compile inside a frozen bundle.
#      (librosa tries to import numba; the stubs/numba/ stub absorbs the
#       import without the real LLVM/JIT machinery — see ADR-0002.)
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # _MEIPASS is the temp dir where PyInstaller unpacks the bundle contents.
    # On macOS with PyInstaller 6 it resolves to Contents/Frameworks/ (not
    # MacOS/) — see CLAUDE.md "danger zones" §3.
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
    # Prepend the directory containing the bundled ffmpeg to PATH AND set
    # FFMPEG_BINARY so ffmpeg-python / imageio call the right binary.
    os.environ["PATH"] = (
        os.path.dirname(_ffmpeg_exe) + os.pathsep + os.environ.get("PATH", "")
    )
    os.environ.setdefault("FFMPEG_BINARY", _ffmpeg_exe)
except Exception:
    pass  # fall back to whatever ffmpeg is on the system PATH

# ---------------------------------------------------------------------------
# Application modules
# ---------------------------------------------------------------------------

# slurmio: filesystem IO layer.
# _new_temp_path is used here in __main__ to write the favicon temp PNG.
# The module also registers the atexit hook and creates SESSION_TMP_DIR
# at import time — both happen exactly once, as intended.
# PYINSTALLER: "slurmio" must stay in hiddenimports in slurmify.spec.
from slurmio import _new_temp_path

# ui_assets: static browser content.
# INIT_JS and CUSTOM_CSS are injected into launch() below.
# _ICON_B64 is used here in __main__ to write the favicon and build <link> tags.
# PYINSTALLER: "ui_assets" must stay in hiddenimports in slurmify.spec.
from ui_assets import (
    INIT_JS,    # ~500 lines of browser JS (Web Audio chain, FX sync, hover gifs)
    CUSTOM_CSS, # ~1 200 lines of Gradio CSS (dark theme, Easter egg animations)
    _ICON_B64,  # base64 PNG: Subvoyant cat icon (favicon + header logo)
)

# slurm_ui: the entire Gradio layout and all event handlers.
# PYINSTALLER: "slurm_ui" must stay in hiddenimports in slurmify.spec.
from slurm_ui import build_ui

# gradio: only needed here for gr.themes.Base() in launch().
import gradio as gr


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ui = build_ui()

    # Gradio 6: inject JS via head= as a real <script> tag.
    # launch(js=) and gr.Blocks(js=) are both unreliable in Gradio 6
    # (they use eval() which breaks on IIFEs in some versions).
    # head= injects raw HTML into <head>, so the browser executes it normally.

    # Google Fonts for the alternate skins.  Loaded for all skins (the
    # browser caches them) but only referenced by the relevant [data-skin] CSS.
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

    # Browser tab icon — Siena cat.  Multi-pronged attack (ADR-0010):
    #   1. Write _ICON_B64 to a temp PNG, pass via favicon_path (Gradio's
    #      documented API; serves the file at /favicon.ico).
    #   2. Inject <link rel="icon"> tags at the END of <head>.
    #   3. JS-based setter that runs after page load AND re-applies on a
    #      timeout (defeats anything Gradio sets post-load).  This is the
    #      one that actually wins — head-injected links and favicon_path
    #      both got overridden in testing.  See ADR-0010 for the full story.
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
    # Re-runs at multiple timeouts to defeat any post-load overrides by Gradio.
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
