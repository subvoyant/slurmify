# ADR-0017: Extract filesystem IO into `slurmio.py` (Phase 3)

- **Status:** Accepted
- **Date:** 2026-05-06

## Context

After Phase 2 (ADR-0016) extracted pure DSP into `slurmcore.py`, `app.py`
stood at ~1,466 lines.  The remaining non-UI code fell into two categories:

1. **Filesystem IO** — resolving asset paths, managing the session temp
   directory, loading audio files, writing audio files.
2. **Gradio UI** — event handlers, slider wiring, `gr.Blocks()` construction,
   video export, quit handling.

The IO layer was scattered across four sections of `app.py`:

| Section | What it contained |
|---|---|
| Lines ~51–61 | `_asset()` — bundle vs. dev path resolution |
| Lines ~64–135 | Session temp dir: `SESSION_TMP_DIR`, `_cleanup_session_tmp`, `atexit.register`, `_sweep_orphan_session_dirs`, `_new_temp_path`, `_reveal_temp_dir` |
| Lines ~148–168 | `SUPPORTED_EXTS`, `TARGET_SR`, `load_audio` |
| Lines ~199–259 | `_SF_FORMATS`, `_FFMPEG_FORMATS`, `_write_audio` |

Mixing IO and UI in the same file made both harder to reason about:

- `_write_audio` contained a local `import subprocess` mid-function — a
  deferred import that existed only to avoid top-level noise in `app.py`.
- `_reveal_temp_dir` contained local `import subprocess` and `import platform`
  for the same reason.
- `load_audio` and `_write_audio` could not be called or tested without
  loading the full Gradio application context.
- `_asset()` had nothing to do with Gradio but lived in the same file.

## Decision

**Extract all filesystem IO into `slurmio.py`.**

`slurmio.py` contains exactly:

| Name | What it is |
|---|---|
| `_asset` | Bundle vs. dev path resolver (unchanged interface) |
| `SESSION_TMP_DIR` | Per-session temp directory string (module-level, set at import time) |
| `_cleanup_session_tmp` | atexit handler — wipes SESSION_TMP_DIR on normal exit |
| `_sweep_orphan_session_dirs` | Startup sweep — deletes prior crashed-run temp dirs |
| `_new_temp_path` | Create a session-scoped temp file (unchanged interface) |
| `_reveal_temp_dir` | Open SESSION_TMP_DIR in the OS file browser (moved from app.py) |
| `SUPPORTED_EXTS` | frozenset of accepted audio/video extensions (unchanged) |
| `TARGET_SR` | 44 100 Hz constant (unchanged) |
| `load_audio` | Load any file → (ndarray, sr) (unchanged interface) |
| `_SF_FORMATS` | soundfile format config dict (unchanged) |
| `_FFMPEG_FORMATS` | ffmpeg transcode config dict (unchanged) |
| `_write_audio` | Write ndarray → temp file (unchanged interface) |

`app.py` imports all twelve names:

```python
from slurmio import (
    _asset,
    SESSION_TMP_DIR,
    _new_temp_path,
    _reveal_temp_dir,
    SUPPORTED_EXTS,
    TARGET_SR,
    load_audio,
    _write_audio,
)
```

`slurmify.spec` gains `"slurmio"` in `hiddenimports`.

## Module-level side effects

`slurmio.py` intentionally runs two statements at import time:

```python
SESSION_TMP_DIR = tempfile.mkdtemp(prefix="slurmify-session-")
atexit.register(_cleanup_session_tmp)
_sweep_orphan_session_dirs()
```

This matches the behaviour that was previously in `app.py` and is correct:
the module is imported once during app startup (after the PyInstaller
bootstrap has set `PATH` and `FFMPEG_BINARY`), creating the session directory
and registering cleanup exactly once.

## Purity rule for `slurmio.py`

`slurmio.py` must never import any of:

```
gradio  pyrubberband  scipy  slurmcore  ui_assets
```

The one allowed exception is the lazy `import gradio as _gr` inside
`_reveal_temp_dir`'s except handler.  This is deferred to call time
deliberately so that PyInstaller's static analysis pass can scan `slurmio.py`
without requiring gradio to be installed in the analysis environment.
(The same technique was already used in the original `app.py` code for the
same reason — see the inline comment in `_reveal_temp_dir`.)

Allowed top-level imports:

```
atexit  glob  os  platform  shutil  subprocess  sys  tempfile
librosa  numpy  soundfile
```

## Why `_reveal_temp_dir` moved to `slurmio.py`

`_reveal_temp_dir` uses `subprocess.Popen` and `platform.system()` — both
are IO/OS operations — and only touches `SESSION_TMP_DIR`, which lives in
`slurmio.py`.  The only Gradio contact is the lazy `_gr.Error` in the error
path, which is a minor exception to an otherwise clean IO function.

Keeping it in `app.py` would have required `app.py` to reference
`SESSION_TMP_DIR` by name after importing it, which works but places the
temp-dir logic in two files.  Co-locating all temp-dir code in `slurmio.py`
is cleaner.

## Local imports promoted to top-level

The original `_write_audio` in `app.py` contained:
```python
import subprocess   # deferred because it was inside a branch
```

And `_reveal_temp_dir` contained:
```python
import subprocess
import platform
```

These were deferred only to keep `app.py`'s top-level import block short.
In `slurmio.py` they are proper top-level imports — no reason to hide them.
The `import gradio as _gr` in `_reveal_temp_dir`'s except handler remains
deferred for the PyInstaller reason described above.

## Updated Four-Module Architecture (Phase 3 complete)

```
app.py        — bootstrap + Gradio event handlers + UI wiring (~1 320 lines)
ui_assets.py  — static browser content (DONE — ADR-0015)
slurmcore.py  — pure audio DSP (DONE — ADR-0016)
slurmio.py    — filesystem IO  (DONE — this ADR)
```

Phase 4 (`slurm_ui.py`) would extract `build_ui`, `process`, `render_video`,
and `_quit_app` into a dedicated UI orchestration module.  That remains future
work; the four-file split is already a major improvement.

After Phase 3, `app.py` is ~1,320 lines (down from 3,569 before Phase 1).

## Consequences

**Wins**

- `slurmio.py` is independently importable without Gradio, slurmcore, or an
  actual audio file on disk — unit tests can import and call `_new_temp_path`,
  `_write_audio`, etc. with mock data.
- All temp-directory lifecycle code (create, atexit, orphan sweep, new path,
  reveal) is co-located in one ~200-line section of `slurmio.py`.
- `app.py` drops from ~1,466 lines (after Phase 2) to ~1,320 lines.
- Local deferred imports (`subprocess`, `platform`) are promoted to top-level
  in `slurmio.py`, making the import graph explicit.

**Costs / risks**

- **One new `hiddenimports` entry** (`"slurmio"`) in `slurmify.spec`.
  If removed, the bundled `.app` crashes on startup with
  `ModuleNotFoundError: slurmio`.  The entry is present and must not be removed.

- **Module-level side effects on import.** `SESSION_TMP_DIR = tempfile.mkdtemp(...)`
  and `atexit.register(...)` and `_sweep_orphan_session_dirs()` run the first
  time `slurmio` is imported.  Test code that imports `slurmio` must be aware
  of this — a temp directory is created and orphan cleanup runs.  This matches
  the prior behaviour (same code was in `app.py`'s module scope).

- **`burn_fx()` still calls `librosa.load()` directly** in `app.py`.  It does
  NOT use `load_audio()` because `load_audio` forces mono and TARGET_SR=44100,
  while `burn_fx` needs to preserve the original stereo layout and native SR
  for the FX chain.  This is intentional and documented in `slurmio.py`'s
  `load_audio` docstring.

## See also

- ADR-0015 — Phase 1 (ui_assets.py extraction)
- ADR-0016 — Phase 2 (slurmcore.py extraction)
- ADR-0011 — original session-scoped temp directory design (now implemented in slurmio.py)
- ADR-0001 — original "single file by design" rationale
- `slurmio.py` — the file created by this decision
