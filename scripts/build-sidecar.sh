#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/build-sidecar.sh — Build the PyInstaller sidecar binary
# ──────────────────────────────────────────────────────────────────────
#
# Produces a standalone Python+FastAPI+DSP bundle under
#   src-tauri/binaries/slurmify-backend-aarch64-apple-darwin/
# which Tauri's externalBin convention copies into the bundled .app's
# Contents/MacOS/ at `pnpm tauri build` time.
#
# Why a shell script and not a one-liner?
#   • PyInstaller has to be invoked from src-python/ so the spec's
#     relative paths resolve correctly (it embeds the SPEC's directory
#     into the bundle metadata).
#   • The output folder name MUST be the rust-target-triple — Tauri's
#     bundler picks the binary whose suffix matches the host triple at
#     build time.  We rename the PyInstaller output here.
#   • Cleaning the previous bundle prevents stale .pyc files from
#     surviving a refactor.
#
# Prereqs:
#   • Python 3.11+ in a venv with pip-installed src-python deps.
#   • PyInstaller in the same venv (added to dev-extras in pyproject;
#     `pip install -e ".[dev]" pyinstaller` to bootstrap).
#
# Usage:
#   ./scripts/build-sidecar.sh                  # build for host arch
#   PY=/path/to/venv/bin/python ./scripts/...   # override python
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail

# Resolve repo root — works whether the script is run from the repo
# root, src-tauri/, or anywhere else.  The script lives in scripts/,
# so repo root is one level up from $0's dir.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT/src-python"

# Pick the Python interpreter.
#
# Priority:
#   1. $PY env var if explicitly set (escape hatch for unusual setups).
#   2. The local venv at src-python/.venv/bin/python if present.
#      This is the common case: a developer who ran the standard
#      `python -m venv src-python/.venv && pip install -e
#      "src-python[dev]"` bootstrap.
#   3. System `python3` on PATH.
#
# Why auto-detect the venv: the build host's bare `python3` often
# resolves to anaconda base / system python / Homebrew python with
# different site-packages than the Slurmify venv.  The most common
# failure mode used to be "ERROR: PyInstaller not installed in this
# Python" — PyInstaller WAS installed (in the venv), just not in the
# bare interpreter that PATH happened to resolve.  Auto-detection
# removes that footgun without breaking the explicit $PY override
# for power users with non-standard layouts.
if [ -z "${PY:-}" ]; then
    LOCAL_VENV_PY="$REPO_ROOT/src-python/.venv/bin/python"
    if [ -x "$LOCAL_VENV_PY" ]; then
        PY="$LOCAL_VENV_PY"
        # Activate the venv for any subprocess PyInstaller spawns.
        # Functionally equivalent to `source .venv/bin/activate` but
        # without the prompt-tweaking side effects.  Setting
        # VIRTUAL_ENV + PATH covers:
        #   • PyInstaller hooks that re-invoke `python` by basename
        #     (they'd otherwise hit whatever's first on the parent
        #     shell's PATH — typically anaconda or system python).
        #   • `pip` invocations inside hooks, which look up `python`
        #     the same way.
        #   • Any `pip install` follow-up the user might run manually
        #     in the same shell — they get the venv, not anaconda.
        # See PEP 405 for the env-var contract `python -m venv`
        # follows; activate just exports these two vars and tweaks
        # PS1 / aliases.  We skip the cosmetic bits.
        export VIRTUAL_ENV="$REPO_ROOT/src-python/.venv"
        export PATH="$VIRTUAL_ENV/bin:$PATH"
        echo "[build-sidecar] Auto-detected venv: $LOCAL_VENV_PY (VIRTUAL_ENV + PATH activated)"
    else
        PY="python3"
        echo "[build-sidecar] No venv at $LOCAL_VENV_PY — falling back to system python3"
    fi
fi

# ── Sanity checks ──────────────────────────────────────────────────────
echo "[build-sidecar] Using $($PY --version) at $(which "$PY")"
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo "[build-sidecar] ERROR: PyInstaller not installed in this Python."
    echo "                 Install with: $PY -m pip install pyinstaller"
    exit 1
fi
if ! "$PY" -c "import librosa, soundfile, fastapi, uvicorn" 2>/dev/null; then
    echo "[build-sidecar] ERROR: Backend deps missing.  Run:"
    echo "                 $PY -m pip install -e \"$REPO_ROOT/src-python[dev]\""
    exit 1
fi

# ── Arch detection ─────────────────────────────────────────────────────
# Tauri expects the binary at binaries/<name>-<rust-triple>.  On Apple
# Silicon hosts the triple is aarch64-apple-darwin; on Intel it's
# x86_64-apple-darwin.  We let `rustc` resolve the host triple
# authoritatively rather than parsing `uname` — keeps the build script
# in sync with whatever Tauri's bundler will look for.
HOST_TRIPLE="$(rustc -vV | sed -n 's/host: //p')"
if [[ -z "$HOST_TRIPLE" ]]; then
    echo "[build-sidecar] ERROR: rustc not found or returned no host triple."
    exit 1
fi
echo "[build-sidecar] Host triple: $HOST_TRIPLE"

# ── Clean prior build ──────────────────────────────────────────────────
# Delete PyInstaller's intermediate dirs + any previous bundle output
# (single file OR folder, depending on whether the prior build was
# onefile or onedir) so nothing stale leaks into this build.
rm -rf "$REPO_ROOT/src-python/build"
rm -rf "$REPO_ROOT/src-python/dist"
rm -rf "$REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"
rm -f  "$REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"
rm -f  "$REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}.symlink"

# ── Build ──────────────────────────────────────────────────────────────
echo "[build-sidecar] Running PyInstaller (onefile)…"
"$PY" -m PyInstaller --noconfirm slurmify-backend.spec

# PyInstaller (onefile mode) writes a single executable file to
# dist/slurmify-backend.  Move it to the path Tauri's externalBin
# resolver expects: binaries/<basename>-<rust-triple>.
mkdir -p "$REPO_ROOT/src-tauri/binaries"
mv "$REPO_ROOT/src-python/dist/slurmify-backend" \
   "$REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"

# Sanity check — Tauri's bundler will fail with a confusing error
# later if the file isn't there or isn't executable.
if [[ ! -x "$REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}" ]]; then
    echo "[build-sidecar] ERROR: expected executable at"
    echo "                       $REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"
    echo "                 but it's missing or not executable."
    exit 1
fi

echo "[build-sidecar] Done."
echo "[build-sidecar] Output: $REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"
echo "[build-sidecar] Smoke-test: $REPO_ROOT/src-tauri/binaries/slurmify-backend-${HOST_TRIPLE}"
