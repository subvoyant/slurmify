"""
src-python/server.py — Slurmify backend entrypoint
─────────────────────────────────────────────────────────────────────

This is the FastAPI sidecar process introduced in v0.2.0 (ADR-0022).
The Tauri Rust shell (src-tauri/src/main.rs) launches this script as a
child process at app startup; the React frontend talks to it over
localhost HTTP and SSE.

The four critical responsibilities:

  1. Pick a free port — random, not fixed.  Avoids "port in use"
     errors when the user already has slurmify running, when port 7860
     is grabbed by another dev server, or when running multiple
     instances.

  2. Print the chosen port to stdout BEFORE uvicorn starts.  The Tauri
     shell parses the first line that matches our `slurmify_ready`
     marker and uses the port to construct API URLs for the frontend.
     Format is JSON: `{"slurmify_ready": true, "port": NNNNN}`.

  3. Configure CORS for the Tauri webview origin.  In Tauri 2 on macOS,
     `tauri://localhost` is the production webview origin.  In dev mode
     Vite serves on http://localhost:1420.  Both are allowed.

  4. Mount the route modules from src-python/api/.  Each module exports
     a `router` that we include here so server.py stays a slim
     orchestration file.

────────────────────────────────────────────────────────────────────────
sys.path setup
────────────────────────────────────────────────────────────────────────
Slurmcore and slurmio live at the repository root, ONE LEVEL UP from
src-python/.  We add the repo root to sys.path so the api modules can
`import slurmcore` / `import slurmio` directly — same import surface
the Gradio app used in v0.1.6.

When PyInstaller bundles the sidecar binary, both src-python/ and the
repo root get included in the bundle and both end up under sys._MEIPASS;
the bootstrap below works in both contexts.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import sys
import tempfile
import time

# ── sys.path bootstrap ──────────────────────────────────────────────────
# Add the repository root (one level above this file) so `import
# slurmcore` / `import slurmio` work.  This must happen BEFORE any
# imports from api/ since those modules import slurmcore.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


# ── Now we can import everything ────────────────────────────────────────
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Local route modules.  Each exports a `router`.
from api import upload, slurmify, fx, render, files, analyze


# ── App construction ────────────────────────────────────────────────────
app = FastAPI(
    title="Slurmify Backend",
    description="FastAPI sidecar for the Tauri/React slurmify frontend (ADR-0022).",
    version="0.2.0",
    # Disable the auto-generated /docs and /redoc endpoints in production
    # — they're useful for development but not needed when the only
    # consumer is our own React frontend running on the same machine.
    # Re-enable by setting SLURM_ENABLE_DOCS=1 in the environment.
    docs_url="/docs" if os.environ.get("SLURM_ENABLE_DOCS") else None,
    redoc_url=None,
)

# ── CORS ────────────────────────────────────────────────────────────────
# Tauri 2 production:  tauri://localhost is the webview's origin.
# Vite dev server:     http://localhost:1420.
# We allow both so dev-mode and production-mode use the same backend
# without code changes.  No wildcard — that's the right discipline for
# a desktop sidecar that only ever serves these two trusted origins.
#
# allow_credentials must be explicit because EventSource (SSE) requires
# `credentials: 'include'` in some browsers when connecting cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",        # Tauri 2 alternate origin on some platforms
        "http://localhost:1420",         # Vite dev default
        "http://127.0.0.1:1420",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# ── Route registration ──────────────────────────────────────────────────
# Order doesn't matter functionally — FastAPI dispatches by path.
# Listed in roughly the order a user-flow hits them.
app.include_router(upload.router)      # POST /upload
app.include_router(analyze.router)     # GET /analyze/{file_id}  — librosa BPM (cached)
app.include_router(slurmify.router)    # POST /slurmify, GET /jobs/{id}/progress
app.include_router(fx.router)          # POST /burn-fx
app.include_router(render.router)      # POST /render-video
app.include_router(files.router)       # GET /files/{id}, GET /files/{id}/download


# ── /health ─────────────────────────────────────────────────────────────
# Tauri's main.rs uses this to detect when the backend has finished
# initializing.  It also serves as a smoke test for `curl localhost:PORT/health`
# during development.
#
# `tmp_dir` is included so the frontend's "📁 reveal temp files" button
# can ask Tauri to open the session-scoped temp directory in Finder
# without us having to add a separate /api/tmp-dir endpoint.

@app.get("/health")
def health() -> dict[str, str | bool]:
    # Lazy import here to avoid a top-of-file circular: slurmio is
    # already loaded by the api modules but this endpoint is the
    # very first one called, before those modules' routers register.
    import slurmio
    return {
        "status":  "ok",
        "version": "0.2.0",
        "ready":   True,
        "tmp_dir": slurmio.SESSION_TMP_DIR,
    }


# ── Port discovery file ─────────────────────────────────────────────────
# In addition to printing the port-on-stdout JSON line (for the
# production Tauri sidecar to parse), we also write a small JSON file
# to a stable path so a separately-launched frontend in dev mode can
# discover the running backend without us having to hand-copy the port.
#
# Lifecycle:
#   • On startup, write {"port": N, "pid": M, "started_at": T} to the
#     discovery path.
#   • On normal exit (atexit), delete the file so a stale port doesn't
#     mislead the next launch.
#   • On crash, the file lingers — but the frontend is expected to do
#     a /health probe before trusting the port (a stale file points at
#     a port nobody answers, the probe times out, the frontend reports
#     "backend not running").
#
# Path choice: we use a stable name inside the system temp dir so it
# survives across user sessions and doesn't litter $HOME.  Tauri's
# Rust shell knows the same path convention.

DISCOVERY_FILE = os.path.join(tempfile.gettempdir(), "slurmify-backend.json")


def write_discovery_file(port: int) -> None:
    """Write the port + pid to DISCOVERY_FILE.  Used by the dev frontend."""
    payload = {
        "port":       port,
        "pid":        os.getpid(),
        "started_at": time.time(),
        "version":    "0.2.0",
    }
    # Atomic write — write to temp then rename, so a polling reader never
    # sees a half-written file.
    tmp_path = DISCOVERY_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f)
    os.replace(tmp_path, DISCOVERY_FILE)


def cleanup_discovery_file() -> None:
    """Delete DISCOVERY_FILE on normal exit so stale ports don't confuse the next run."""
    try:
        os.unlink(DISCOVERY_FILE)
    except OSError:
        pass


atexit.register(cleanup_discovery_file)


# ── Signal handlers — make Tauri-shutdown clean up temp files ──────────
# Slurmio's SESSION_TMP_DIR auto-cleans via atexit (ADR-0011), and so
# does our discovery file (above).  But atexit runs only on NORMAL
# Python interpreter exit — sys.exit(), end of script, or KeyboardInterrupt.
# SIGTERM (which Tauri sends to the sidecar when the user quits the
# app) bypasses atexit entirely, leaving temp files orphaned in
# /var/folders/.../T/slurmify-session-*.
#
# Fix: convert SIGTERM into a clean sys.exit() so atexit handlers run.
# Same for SIGINT (Ctrl-C in dev) — already handled by Python's
# default but explicit for clarity.
#
# With this in place, every slurm output file (and the session dir
# itself) is wiped the moment the user quits Slurmify.  Files the
# user has explicitly saved elsewhere (via the future "export"
# button or by drag-out) are untouched — those live in user-chosen
# paths, not SESSION_TMP_DIR.

def _shutdown_signal_handler(signum: int, _frame) -> None:
    """Convert a termination signal into a clean Python exit.

    Calling sys.exit() raises SystemExit, which is caught by the
    interpreter shutdown sequence — that sequence DOES run atexit
    handlers.  Result: SESSION_TMP_DIR gets rmtree'd on Tauri quit
    just like it would on Ctrl-C.
    """
    print(f"[slurm-api] received signal {signum}, shutting down cleanly", flush=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _shutdown_signal_handler)
# SIGHUP is sent when the controlling terminal closes (rare in our
# setup but free to handle).  SIGINT is already handled by Python's
# default KeyboardInterrupt → atexit path; no override needed.
try:
    signal.signal(signal.SIGHUP, _shutdown_signal_handler)
except (AttributeError, OSError):
    # SIGHUP doesn't exist on Windows; ignore.
    pass


# ── Free port selection ─────────────────────────────────────────────────

def find_free_port() -> int:
    """Bind to port 0 to let the OS pick an unused port, then release it.

    There's a tiny race window where another process could grab the
    port between our `close()` and uvicorn's `bind()`, but in practice
    on macOS the kernel doesn't reuse a recently-released port within
    the milliseconds it takes uvicorn to bind.  If it ever bites in
    the wild, the failure mode is uvicorn raising OSError at startup;
    Tauri's main.rs would surface that as a "backend failed to start"
    error and the user could relaunch.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    """Pick a port, print it as JSON to stdout, then run uvicorn.

    The JSON-on-stdout pattern is intentional — it gives the Tauri shell
    a deterministic line to parse without having to grep uvicorn's own
    log output.  The shell waits for a line containing `"slurmify_ready"`
    and reads the `port` field from it.

    Stdout is flushed explicitly because Python's default line buffering
    can hold the line in a pipe buffer when stdout is a pipe (which it
    is when Tauri spawns us as a child process).
    """
    port = find_free_port()

    # 1. Print JSON to stdout — this is what the production Tauri sidecar
    #    parses to learn the port (see ADR-0022 §6.2).
    ready_line = json.dumps({"slurmify_ready": True, "port": port})
    print(ready_line, flush=True)

    # 2. Write the same info to a discovery file under the system temp
    #    dir so a dev-mode frontend (pnpm tauri dev) can find us without
    #    needing stdout pipe access.
    write_discovery_file(port)

    # log_level="warning" keeps uvicorn's startup banner / per-request
    # access logs out of stdout — useful so the Tauri shell's stdout
    # parser doesn't have to filter through them.
    #
    # In dev mode (SLURM_DEV=1), we crank logging up so curl-debugging
    # is easier.
    log_level = "info" if os.environ.get("SLURM_DEV") else "warning"

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=log_level,
        # Disable uvicorn's own access log; we don't want it racing our
        # JSON ready line on stdout.
        access_log=bool(os.environ.get("SLURM_DEV")),
    )


if __name__ == "__main__":
    main()
