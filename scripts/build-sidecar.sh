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

# Pick the Python interpreter.  Default to whatever `python3` resolves
# to, but allow override via $PY for users with custom venvs.
PY="${PY:-python3}"

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
