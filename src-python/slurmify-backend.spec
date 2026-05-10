# ──────────────────────────────────────────────────────────────────────
# src-python/slurmify-backend.spec — PyInstaller bundle of the FastAPI sidecar
# ──────────────────────────────────────────────────────────────────────
#
# Produces a SINGLE-FILE Mach-O binary at
#   ../src-tauri/binaries/slurmify-backend-aarch64-apple-darwin
# (Tauri's externalBin contract requires a single file at that exact
# path — onedir folders aren't supported by externalBin in Tauri 2.)
#
# Why onefile, not onedir?
#   • Tauri's externalBin / shell-plugin sidecar resolves to ONE file.
#     Onedir produces a folder of .py + .so + executable; Tauri can't
#     bundle a folder via externalBin without bespoke resource-dir
#     plumbing on the Rust side.
#   • Onefile self-extracts to /tmp on each launch (3-5 s cold start);
#     in exchange we get a clean single-binary path that bundles into
#     Contents/MacOS/slurmify-backend-<triple> automatically.
#   • The startup hit is acceptable for a tester DMG.  Production
#     polish (faster startup, smaller bundle) can revisit this with
#     resource-dir spawning later.
#
# Why these hiddenimports?
#   librosa lazy-loads its decoders + cache backends via importlib at
#   runtime, so PyInstaller's static analysis misses them.  The list
#   below is the empirical "what librosa actually touches" set —
#   trimmed down by running the sidecar with PYINSTALLER_VERBOSE_IMPORTS
#   and watching for ImportError on first slurmify call.  scipy.signal
#   is a similar story.  fastapi + starlette are well-behaved.
#
# Why these collect_data_files?
#   librosa ships small audio fixtures (example clips) that get loaded
#   by various decoders; soundfile bundles libsndfile under its
#   _soundfile_data/ tree.  Both must be copied into the bundle or
#   imports succeed but reads fail at runtime.
#
# Build:
#   cd src-python
#   pyinstaller --noconfirm slurmify-backend.spec
# (Driven from scripts/build-sidecar.sh in normal use.)
# ──────────────────────────────────────────────────────────────────────

# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


# ── Paths ───────────────────────────────────────────────────────────────
# This spec lives in src-python/ and is invoked from there.  The
# slurmcore + slurmio modules live one level up at the repo root; we
# add the repo root to PyInstaller's `pathex` so they're discoverable
# at analysis time, and we list them as `hiddenimports` so they end up
# in the bundle even though server.py only imports them transitively
# through api/*.py.
SPEC_DIR  = os.path.dirname(os.path.abspath(SPEC))     # noqa: F821 (PyInstaller globals)
REPO_ROOT = os.path.dirname(SPEC_DIR)


# ── Hidden imports ──────────────────────────────────────────────────────
# librosa loads decoders, plotters, and feature extractors via importlib
# at runtime.  collect_submodules walks the whole package and grabs them
# all — heavyweight, but reliable.  We trim the obvious bloat (display,
# tests) afterward.
hidden = []
hidden += collect_submodules("librosa")
hidden += collect_submodules("soundfile")
hidden += collect_submodules("scipy.signal")
hidden += collect_submodules("scipy.interpolate")
hidden += collect_submodules("scipy.io")
hidden += collect_submodules("scipy.special")
hidden += collect_submodules("scipy.fft")
hidden += collect_submodules("scipy.sparse")
hidden += collect_submodules("scipy.linalg")
hidden += collect_submodules("scipy.ndimage")
hidden += collect_submodules("numpy")
hidden += collect_submodules("audioread")     # librosa fallback decoder
hidden += collect_submodules("soxr")          # librosa resampler
hidden += collect_submodules("pyrubberband")
hidden += collect_submodules("samplerate")    # alt resampler some hosts pull
hidden += collect_submodules("pooch")         # librosa example-fixture cache
hidden += collect_submodules("lazy_loader")   # librosa's lazy import system
hidden += collect_submodules("decorator")     # librosa decorators

# FastAPI + uvicorn
hidden += collect_submodules("fastapi")
hidden += collect_submodules("starlette")
hidden += collect_submodules("uvicorn")
hidden += collect_submodules("anyio")
hidden += collect_submodules("h11")
hidden += collect_submodules("httptools")
hidden += collect_submodules("websockets")
hidden += collect_submodules("watchfiles")
hidden += collect_submodules("sse_starlette")
hidden += collect_submodules("multipart")     # python-multipart

# Drop the obvious dev-only / heavy bloat that we definitely don't use
# at runtime.  Each filter shrinks the bundle and speeds startup.
SKIP_PREFIXES = (
    "librosa.display",          # matplotlib pulls in 100+ MB
    "librosa.tests",
    "scipy.linalg.tests",
    "scipy.signal.tests",
    "numpy.tests",
    "numpy.f2py",
    "starlette.testclient",
    "uvicorn.workers",          # only used in production gunicorn deploys
)
hidden = [m for m in hidden if not any(m.startswith(p) for p in SKIP_PREFIXES)]

# Project modules — ensure server, jobs, api/*, slurmcore, slurmio all
# end up in the bundle.  api/* is auto-discovered via collect_submodules.
hidden += collect_submodules("api")
hidden += ["server", "jobs", "slurmcore", "slurmio"]


# ── Data files ──────────────────────────────────────────────────────────
# Native-extension data trees that PyInstaller's binary scanner alone
# can't relocate (libsndfile inside soundfile, librosa fixtures + LFS
# cache, etc.).  Without these, imports succeed but functions raise at
# call time when looking for a sibling file.
datas = []
datas += collect_data_files("librosa")
datas += collect_data_files("soundfile")
datas += collect_data_files("audioread")
datas += collect_data_files("pooch")
datas += collect_data_files("lazy_loader")
datas += collect_data_files("scipy")          # scipy ships small data tables

# Package metadata — fastapi and a few deps inspect their own
# importlib.metadata at runtime (e.g., to render the version banner);
# missing METADATA / RECORD trips an "package not found" exception.
datas += copy_metadata("fastapi")
datas += copy_metadata("starlette")
datas += copy_metadata("uvicorn")
datas += copy_metadata("sse_starlette")
datas += copy_metadata("librosa")
datas += copy_metadata("soundfile")

# ── Slurmify project assets ─────────────────────────────────────────────
# The sidecar's render-video pipeline stream-copies a pre-encoded loop
# MP4 from the project-root `assets/` folder (see ADR-0006).  In dev
# mode `_asset()` resolves that to `<repo_root>/assets/<file>` via
# `os.path.dirname(__file__)`; in a frozen bundle it resolves to
# `<sys._MEIPASS>/assets/<file>` (see slurmio._asset).  PyInstaller
# never copies these on its own — datas has to call them out.
#
# Required-by-runtime today:
#   • assets/siebaSlurm_A003.mp4   — YouTube-loop video (api/render.py)
#
# Bundled defensively (cheap; future-proofs new _asset() callers):
#   • assets/siena_dancer.gif      — currently loaded by React via Vite,
#                                    not by the sidecar — but if we ever
#                                    add a server-side preview render,
#                                    it'll need this on disk.
#   • assets/subvoyant_bug.png     — same rationale.
#
# Build-time guard: assert the required-by-runtime file actually exists
# on the build host BEFORE PyInstaller starts copying.  This matches
# the posture of the ffmpeg + rubberband checks below: a missing asset
# should fail the build loudly, not produce a silently-broken DMG.
# (The original v0.2.0 build shipped without this section and tester
# Max hit "Missing animation loop — assets/siebaSlurm_A003.mp4 not
# found." on the first render-video click; this guard exists so that
# never happens again.)
_ASSETS_DIR = os.path.join(REPO_ROOT, "assets")
_REQUIRED_ASSETS = ["siebaSlurm_A003.mp4"]
for _required in _REQUIRED_ASSETS:
    _full = os.path.join(_ASSETS_DIR, _required)
    if not os.path.isfile(_full):
        raise SystemExit(
            f"[slurmify-spec] ERROR: required asset missing at build time: {_full}\n"
            f"  The sidecar's render-video pipeline stream-copies this file;\n"
            f"  shipping the bundle without it would crash render-video on\n"
            f"  every click.  Restore the file (it lives in git LFS / the\n"
            f"  graphic/ working folder) and rebuild."
        )

# Tuple form is `(src_absolute_path, dst_directory_in_bundle)`.  We mirror
# the source layout — `<bundle>/assets/<file>` — so `_asset("assets/...")`
# resolves correctly in both dev and frozen modes.
for _name in os.listdir(_ASSETS_DIR):
    _src = os.path.join(_ASSETS_DIR, _name)
    if os.path.isfile(_src) and not _name.startswith("."):  # skip .DS_Store
        datas.append((_src, "assets"))
        print(f"[slurmify-spec] bundling asset assets/{_name}")


# ── Native binaries ─────────────────────────────────────────────────────
# Some packages ship native dylibs (libsndfile.dylib, libsoxr.dylib)
# alongside the .py files.  collect_dynamic_libs grabs them.
binaries = []
binaries += collect_dynamic_libs("soundfile")
binaries += collect_dynamic_libs("soxr")
binaries += collect_dynamic_libs("scipy")
binaries += collect_dynamic_libs("numpy")

# ── Bundle ffmpeg ───────────────────────────────────────────────────────
# librosa's audioread fallback (used when libsndfile can't decode
# AAC/m4a/mp4/opus) shells out to ffmpeg.  Without ffmpeg in the bundle
# the fallback either fails outright or hangs exhausting other backends.
# We resolve the build-host's ffmpeg via shutil.which() and copy it into
# the bundle root; server.py prepends sys._MEIPASS to PATH at runtime so
# audioread + api/upload.py's shutil.which("ffmpeg") both find it.
#
# If ffmpeg isn't installed at build time, we abort with a clear error
# rather than ship a broken bundle silently — m4a is the most common
# audio file format users will throw at the app, so missing ffmpeg
# turns slurmify into "WAV-only" without warning.
import shutil as _shutil
_ffmpeg_path = _shutil.which("ffmpeg")
if not _ffmpeg_path:
    raise SystemExit(
        "[slurmify-spec] ERROR: ffmpeg not found on PATH at build time.\n"
        "  Install it before running build-sidecar.sh:\n"
        "    brew install ffmpeg\n"
        "  (Or override the spec's lookup if you're cross-building.)"
    )
print(f"[slurmify-spec] bundling ffmpeg from {_ffmpeg_path}")
# PyInstaller binary entry: (src_path, dst_in_bundle).  "." puts it
# next to the executable inside the _MEI runtime dir.
binaries.append((_ffmpeg_path, "."))


# ── Bundle rubberband-cli ──────────────────────────────────────────────
# slurmcore.py uses pyrubberband for time-stretch + pitch-shift; the
# Python wrapper shells out to a binary literally named `rubberband`
# on PATH (see pyrubberband/pyrb.py: __RUBBERBAND_UTIL = 'rubberband').
# Despite the runtime error wording — "Please verify that rubberband-cli
# is installed" — the binary it actually invokes is `rubberband`, NOT
# `rubberband-cli`.  Homebrew installs both names from the same formula.
#
# In v0.1.x (slurmify.spec) this binary was bundled into the .app's
# `bin/` subdir and app.py prepended that subdir to PATH on startup.
# v0.2.0 took a different approach for ffmpeg — bundle at "." (the
# bundle root), since server.py already prepends sys._MEIPASS itself
# to PATH at runtime.  The same pattern works here, but the original
# v0.2.0 spec FORGOT to apply it to rubberband, so the slurmify call
# raised RuntimeError on every input file.  This block restores parity
# with v0.1.x.
#
# PyInstaller's macOS binary analyzer (otool) walks the rubberband
# CLI's dylib dependencies and copies librubberband.<n>.dylib (and
# its transitive deps — libsamplerate, libsndfile if linked, libfftw,
# etc.) alongside the binary automatically.  We don't need a separate
# collect_dynamic_libs("rubberband") call — there's no Python package
# of that name to collect from.
#
# If rubberband isn't installed at build time, abort with a clear
# error rather than ship a broken bundle silently — same posture as
# the ffmpeg check above.
_rubberband_path = _shutil.which("rubberband")
if not _rubberband_path:
    raise SystemExit(
        "[slurmify-spec] ERROR: rubberband not found on PATH at build time.\n"
        "  Install it before running build-sidecar.sh:\n"
        "    brew install rubberband\n"
        "  pyrubberband (used by slurmcore for time-stretch + pitch-shift)\n"
        "  shells out to the rubberband CLI; without it, slurmify() raises\n"
        "  RuntimeError on every input file with the misleading message\n"
        "  'Failed to execute rubberband. Please verify that rubberband-cli\n"
        "  is installed.' — even though the binary it looks for is called\n"
        "  `rubberband` (no -cli suffix)."
    )
print(f"[slurmify-spec] bundling rubberband from {_rubberband_path}")
binaries.append((_rubberband_path, "."))


# ── Analysis ────────────────────────────────────────────────────────────
a = Analysis(                                  # noqa: F821
    ["server.py"],
    pathex=[SPEC_DIR, REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluded modules — never imported, but PyInstaller's static
    # analyzer pulls them anyway because they sit inside scipy/librosa.
    # Excluding shaves ~50 MB off the bundle.
    excludes=[
        "matplotlib",
        "matplotlib.pyplot",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "IPython",
        "jupyter",
        "notebook",
        "pandas",
        "sklearn",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)  # noqa: F821


# ── EXE (onefile) ───────────────────────────────────────────────────────
# `console=True` keeps stdout/stderr open so Rust can read the
# "slurmify_ready" JSON line on launch.  `name="slurmify-backend"` is
# the binary the Tauri sidecar invokes — must match the externalBin
# basename in tauri.conf.json (without the platform-triple suffix; the
# build-sidecar.sh script renames the file to add the suffix Tauri
# needs).
#
# Onefile mode: a.binaries + a.zipfiles + a.datas are inlined into
# the EXE call (NOT a separate COLLECT).  `exclude_binaries=False`
# (the default) tells PyInstaller's bootloader to embed everything
# into the executable; on first launch the bootloader extracts to
# a temp dir, then runs the embedded Python.
#
# `runtime_tmpdir=None` lets the bootloader pick its own temp path
# (defaults to platform standard — /var/folders/.../T/_MEI<random>
# on macOS).  Setting an explicit path is occasionally useful for
# avoiding TMP-cleaner races, but the defaults are fine.
exe = EXE(                                     # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="slurmify-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX often breaks Mach-O; not worth the saving
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,         # build for the host arch (arm64 on M-series)
    codesign_identity=None,   # signed later by Tauri's bundler if configured
    entitlements_file=None,
)
