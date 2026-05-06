# ADR-0011: Session-scoped temp directory + atexit + orphan sweep

- **Status:** Accepted
- **Date:** 2026-05 (v0.1.0)

## Context

Every slurmify run, every burn-FX, every YouTube video export creates
a new temp file in the system temp directory via `tempfile.mkstemp()`.
None of them were being cleaned up. On macOS the system tmpdir is
`/var/folders/.../T/` and is only swept periodically by the OS — files
older than 3 days become eligible for cleanup, but the sweep only runs
on reboot or maintenance windows. A user who slurmified 50 times in a
day could easily accumulate a gigabyte or more of stranded files.

Constraints:

- **Don't delete files mid-session.** The user might still be playing
  back / downloading the most recent output when they trigger another
  slurmify.
- **Handle crashes.** If the Python process dies before atexit runs
  (`SIGKILL`, OOM, force-quit), the cleanup never fires.
- **Multi-instance safety.** A user might run two Slurmify instances
  simultaneously; cleanup of one shouldn't touch the other's files.

## Decision

**Per-process session subdirectory under the system tmpdir, atexit
cleanup of just our subdir, and an orphan sweep on next launch for
crashed prior sessions.**

```python
SESSION_TMP_DIR = tempfile.mkdtemp(prefix="slurmify-session-")

def _cleanup_session_tmp():
    shutil.rmtree(SESSION_TMP_DIR, ignore_errors=True)
atexit.register(_cleanup_session_tmp)

def _sweep_orphan_session_dirs():
    """Delete leftover slurmify-session-* dirs from prior crashed runs."""
    pattern = os.path.join(tempfile.gettempdir(), "slurmify-session-*")
    for old_dir in glob.glob(pattern):
        if old_dir == SESSION_TMP_DIR:
            continue
        try:
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)
        except Exception:
            pass
_sweep_orphan_session_dirs()

def _new_temp_path(suffix, prefix="slurmify_"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix,
                                 dir=SESSION_TMP_DIR)
    os.close(fd)
    return path
```

All five `tempfile.mkstemp()` / `NamedTemporaryFile()` call sites in
the codebase (in `_write_audio`, `render_video`, the favicon writer,
the FX intermediate WAV, and the universal-upload extraction) were
converted to use `_new_temp_path()`. New code that creates temp files
must use this helper too.

## Consequences

**Wins**

- **Disk gets every byte back on normal quit.** atexit fires when the
  Python process exits cleanly (including from the in-app Quit button,
  Cmd-Q, Ctrl-C, etc.).
- **Self-healing for crashes.** Even if atexit didn't fire (SIGKILL,
  power loss), the next launch's orphan sweep cleans up the old
  session dir.
- **Multi-instance safe.** Each instance has its own session dir; the
  orphan sweep only removes dirs that aren't the current process's.
  Two instances running at the same time both keep their own files
  alive until they each exit.
- **Future temp-file additions are auto-cleaned** as long as they go
  through `_new_temp_path()` — there's a single chokepoint.

**Costs**

- **Files don't survive a session.** A user who renders something,
  closes Slurmify, then realizes they wanted that file is out of
  luck unless they downloaded it through the browser first. Mitigated
  by: (a) the "📁 reveal temp files" button so users can grab files
  before quit, and (b) Gradio's own download-button on every audio/
  video output component.
- **Mid-session accumulation is still possible.** A power user
  running 100s of slurmifies in one session accumulates files until
  they quit. We don't currently LRU-cap. If this becomes a pain
  point, add: keep the last N files in the session dir and delete
  older ones on each new write.

## Risks

- **`tempfile.gettempdir()` returns different paths on different
  platforms.** Implementation is platform-agnostic via stdlib, but
  the orphan-sweep glob needs to keep matching the exact prefix we
  create with — keep `prefix="slurmify-session-"` on both ends in sync.
- **`shutil.rmtree(ignore_errors=True)`** silently swallows permission
  errors. If a future change writes files into the session dir under
  a different uid (e.g. spawning a subprocess that runs as another
  user), cleanup might silently fail. Currently no such case.

## See also

- `app.py` `SESSION_TMP_DIR` setup near top of module
- `_new_temp_path` — the single chokepoint for any new temp file
- `_reveal_temp_dir` — the UI button that opens the session dir in
  the OS file browser, useful for grabbing files before quit
