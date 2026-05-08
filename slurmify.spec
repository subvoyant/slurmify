# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Slurmify.app
Build with:  pyinstaller slurmify.spec
"""

import subprocess
import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Locate native binaries
# ---------------------------------------------------------------------------

def find_bin(name):
    """Return the absolute path to a binary, or raise a clear error."""
    try:
        path = subprocess.check_output(["which", name], stderr=subprocess.DEVNULL).decode().strip()
        if path:
            return path
    except subprocess.CalledProcessError:
        pass
    raise RuntimeError(
        f"\n\n  '{name}' not found on PATH.\n"
        f"  Run:  brew install {name}\n"
    )

rubberband_bin = find_bin("rubberband")
print(f"[spec] rubberband → {rubberband_bin}")

# ffmpeg comes from imageio-ffmpeg (bundled static binary) — no Homebrew ffmpeg needed.
try:
    import imageio_ffmpeg as _iio
    ffmpeg_bin = _iio.get_ffmpeg_exe()
    print(f"[spec] ffmpeg     → {ffmpeg_bin} (imageio-ffmpeg)")
except ImportError:
    ffmpeg_bin = find_bin("ffmpeg")
    print(f"[spec] ffmpeg     → {ffmpeg_bin} (system)")

# ---------------------------------------------------------------------------
# Collect package data (gradio ships a LOT of static web assets)
# ---------------------------------------------------------------------------

gradio_datas,        gradio_bins,        gradio_hidden        = collect_all("gradio")
gradio_client_datas, gradio_client_bins, gradio_client_hidden = collect_all("gradio_client")

# safehttpx and groovy are Gradio dependencies that read version.txt from their
# package directories at runtime. collect_all ensures those files are bundled.
safehttpx_datas, safehttpx_bins, safehttpx_hidden = collect_all("safehttpx")
groovy_datas,    groovy_bins,    groovy_hidden    = collect_all("groovy")

# librosa ships its own example files + numba cache dirs — grab data only
librosa_datas = collect_data_files("librosa", includes=["**/*"])

# ---------------------------------------------------------------------------
# Hidden imports — libraries PyInstaller's static analysis misses
# ---------------------------------------------------------------------------

hidden = [
    # gradio / networking stack
    *gradio_hidden,
    *gradio_client_hidden,
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "starlette.routing",
    "anyio",
    "anyio._backends._asyncio",
    "httpx",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    # audio stack
    "librosa",
    "librosa.core",
    "librosa.core.audio",
    "librosa.core.spectrum",
    "librosa.effects",
    "librosa.beat",
    "librosa.onset",
    "librosa.util",
    "librosa.filters",
    "audioread",
    "audioread.ffdec",
    "soundfile",
    "pyrubberband",
    "imageio_ffmpeg",
    # scipy (librosa dependency, lots of submodules)
    *collect_submodules("scipy"),
    # numba stub — librosa tries to import numba at processing time;
    # we bundle a lightweight no-op stub from stubs/numba/ instead of the real package.
    "numba",
    # sklearn (optional librosa dep — include to avoid runtime warnings)
    "sklearn",
    "sklearn.utils",
    # misc
    "pooch",
    "decorator",
    "lazy_loader",
    "soxr",
    "resampy",
    "msgpack",
    "aiofiles",
    "orjson",
    # local modules — PyInstaller's static analysis does not auto-detect
    # imports of local .py files the way it detects installed packages.
    # Each local module extracted from app.py must be listed here explicitly
    # or the bundled .app will crash on startup with ModuleNotFoundError.
    "ui_assets",    # static browser content: INIT_JS, CUSTOM_CSS, base64 assets
    "slurmcore",    # pure DSP engine: detect_slice_points, slurmify, apply_fx, _fx_*
    "slurmio",      # filesystem IO: _asset, load_audio, _write_audio, session-temp
    "slurm_ui",     # Gradio UI orchestration: build_ui, process, burn_fx, render_video
    "pydantic",
    "pydantic.deprecated",
    "pydantic.deprecated.class_validators",
    "pydantic_core",
    "tomlkit",
    "ruff",
    "packaging",
    "typing_extensions",
    "safehttpx",
    *safehttpx_hidden,
    "groovy",
    *groovy_hidden,
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    ["app.py"],
    pathex=["stubs"],   # makes our numba stub visible to PyInstaller's import scan
    binaries=[
        # Place native CLI tools in a 'bin/' subdir inside the bundle.
        # app.py's bootstrap code prepends this dir to PATH at startup.
        (rubberband_bin, "bin"),
        (ffmpeg_bin,     "bin"),
        *gradio_bins,
        *gradio_client_bins,
        *safehttpx_bins,
        *groovy_bins,
    ],
    datas=[
        *gradio_datas,
        *gradio_client_datas,
        *safehttpx_datas,
        *groovy_datas,
        *librosa_datas,
        ("assets",  "assets"),   # Siena dancer GIF and any future UI assets
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy ML frameworks not needed here — keep bundle lean
        "torch",
        "tensorflow",
        "jax",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        # numba is NOT excluded — we bundle a lightweight stub from stubs/numba/
        # so librosa's runtime import succeeds without the real JIT machinery.
        "llvmlite",    # still exclude the LLVM backend (enormous, not needed by stub)
    ],
    noarchive=False,
    optimize=0,   # do NOT optimize — bytecode optimisation breaks lazy-loaded modules (zlib header mismatch)
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SIENASlurmer",            # internal executable name (no spaces)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt native extensions on macOS — leave off
    console=False,      # no terminal window; Gradio UI lives in the browser
    disable_windowed_traceback=False,
    target_arch=None,   # inherit host arch (arm64 on Apple Silicon)
    codesign_identity=None,   # signing done in build.sh after collection
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SIENASlurmer",
)

app = BUNDLE(
    coll,
    name="Subvoyant SIENA Slurmer.app",
    icon="icon/icons/subvoyant.icns",
    bundle_identifier="com.subvoyant.siena.slurmer",
    info_plist={
        "CFBundleName":               "SIENA Slurmer",
        "CFBundleDisplayName":        "Subvoyant SIENA Slurmer",
        "CFBundleShortVersionString": "0.1.6",
        "CFBundleVersion":            "0.1.6",
        "CFBundleIdentifier":         "com.subvoyant.siena.slurmer",
        "NSHighResolutionCapable":    True,
        "NSPrincipalClass":           "NSApplication",
        "NSAppleScriptEnabled":       False,
        "LSMinimumSystemVersion":     "13.0",
        # LSUIElement = False → shows in Dock while running (friendlier for beta)
        "LSUIElement":                False,
    },
)
