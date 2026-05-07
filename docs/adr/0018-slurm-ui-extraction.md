# ADR-0018: Extract Gradio UI orchestration into `slurm_ui.py` (Phase 4)

- **Status:** Accepted
- **Date:** 2026-05-06

## Context

After Phase 3 (ADR-0017) extracted filesystem IO into `slurmio.py`, `app.py`
stood at ~1,320 lines.  The remaining code fell into two categories:

1. **Gradio UI orchestration** — event handlers (`burn_fx`, `process`,
   `render_video`, `_quit_app`), layout construction (`build_ui`), and helper
   functions (`_leetify`, `_jumble_name`, `_safe_title`, `__version__`,
   `_LEET_PAIRS`, `_AUDIO_EXTS`).
2. **Bootstrap + launch** — PyInstaller path wiring, imageio-ffmpeg env setup,
   and the `if __name__ == "__main__":` launch block (favicon, fonts, `head=`,
   `ui.launch()`).

Keeping both in `app.py` created several problems:

- `build_ui` (~635 lines) dominated the file, making it hard to navigate to
  the bootstrap or launch logic.
- `render_video`, `burn_fx`, and `process` could not be unit-tested or
  imported without dragging in the entire Gradio layout.
- The bootstrap code was buried after ~1,200 lines of UI code; a developer
  debugging launch behaviour had to scroll past the entire UI to reach it.
- Local deferred imports (`json`, `shutil`, `subprocess`, `threading`,
  `datetime`, `random`) inside `render_video`, `_quit_app`, and `_randomize_all`
  obscured the module's true dependency footprint.

## Decision

**Extract all Gradio UI orchestration into `slurm_ui.py`.**

`slurm_ui.py` contains exactly:

| Name | What it is |
|---|---|
| `__version__` | Canonical version string (also referenced in render_video metadata) |
| `_LEET_PAIRS` | Look-alike letter/digit substitution table |
| `_AUDIO_EXTS` | frozenset of extensions routed directly to audio_in (no ffmpeg) |
| `_leetify()` | Randomly transpose look-alike pairs in a char list |
| `_jumble_name()` | Slurm the source filename into a chaotic 16-char suffix |
| `_safe_title()` | Sanitize a user-typed title for use in a filename |
| `burn_fx()` | Gradio handler: load audio → apply_fx → write file |
| `render_video()` | YouTube-ready MP4 export (ffmpeg + PATCH metadata blob) |
| `process()` | Main slurmify pipeline Gradio entry point |
| `_quit_app()` | Graceful server shutdown via threading.Timer + os._exit |
| `build_ui()` | Constructs and returns the complete gr.Blocks layout |

`app.py` after Phase 4 contains only:

| What | Why it stays |
|---|---|
| Module docstring | Orientation comment |
| `import os, sys, base64` | Stdlib needed by bootstrap and `__main__` |
| PyInstaller bootstrap block | Must run before any library import |
| imageio-ffmpeg PATH wiring | Must run before any library import |
| `from slurmio import _new_temp_path` | Used in `__main__` to write the favicon temp PNG |
| `from ui_assets import INIT_JS, CUSTOM_CSS, _ICON_B64` | Injected into `launch()` |
| `from slurm_ui import build_ui` | The only UI call site in app.py |
| `import gradio as gr` | `gr.themes.Base()` in `launch()` |
| `if __name__ == "__main__":` block | Favicon setup + `ui.launch()` |

`slurmify.spec` gains `"slurm_ui"` in `hiddenimports`.

## Local imports promoted to top-level

The original `app.py` contained deferred imports inside function bodies:

```python
# inside render_video():
import json
import shutil
import subprocess
from datetime import datetime, timezone

# inside _quit_app():
import threading

# inside _randomize_all():
import random as _r
```

These were deferred only to reduce visual noise in `app.py`'s already-long
import block.  In `slurm_ui.py` they are all proper top-level imports.  The
module's dependency footprint is now explicit rather than hidden inside
function bodies.

## `_AUDIO_EXTS` promoted from local to module-level

`_AUDIO_EXTS` was previously a local variable inside `build_ui()`'s scope
(defined just before the `_route_upload` nested function that uses it).
Moving it to module-level makes it visible to test code and any future caller
without having to reach inside the closure.  Its value is unchanged.

## `_randomize_all` local `random as _r` alias removed

The alias `_r` existed only to avoid shadowing a hypothetical `random`
variable in the enclosing `build_ui` scope.  At module-level there is no
naming conflict, so the standard `random.choice(...)` / `random.uniform(...)`
calls are used directly.  Behaviour is identical.

## Purity rule for `slurm_ui.py`

`slurm_ui.py` must never import any of:

```
app  slurmify.spec
```

(Importing from `app.py` would create a circular dependency.)

Allowed top-level imports from local modules:

```
slurmio   slurmcore   ui_assets
```

`slurm_ui.py` IS allowed to import `gradio`, `librosa`, and `numpy` at the
top level — it is the UI orchestration layer and those are legitimate
direct dependencies.

## Updated Five-Module Architecture (Phase 4 complete)

```
app.py       — bootstrap + imageio-ffmpeg wiring + __main__ launch (~199 lines)
slurm_ui.py  — Gradio UI: layout, handlers, video export (DONE — this ADR)
ui_assets.py — static browser content (DONE — ADR-0015)
slurmcore.py — pure audio DSP (DONE — ADR-0016)
slurmio.py   — filesystem IO  (DONE — ADR-0017)
```

All four modularisation phases are now complete.  The original monolithic
`app.py` (3,569 lines before Phase 1) has been reduced to a 199-line
bootstrap + entry point.

## Consequences

**Wins**

- `app.py` is now 199 lines — the PyInstaller bootstrap and launch logic
  are immediately readable without scrolling past the UI.
- `slurm_ui.py` can be imported and tested independently of `app.py`.
  In particular, `build_ui()`, `process()`, `burn_fx()`, and `render_video()`
  can be called in a test harness without triggering the PyInstaller bootstrap
  or the favicon setup.
- All deferred imports in function bodies are promoted to module-level,
  making `slurm_ui.py`'s dependency footprint explicit.
- `_AUDIO_EXTS` and `_randomize_all` are now module-level, making them
  accessible to future tests or callers.

**Costs / risks**

- **One new `hiddenimports` entry** (`"slurm_ui"`) in `slurmify.spec`.
  If removed, the bundled `.app` crashes on startup with
  `ModuleNotFoundError: slurm_ui`.  The entry is present and must not be
  removed.

- **`__version__` lives in `slurm_ui.py`**, not `app.py`.  The version bump
  checklist in `CLAUDE.md` already lists `slurm_ui.py` as the source of
  truth for `__version__`.  The `slurm-tag` `<div>` in `build_ui()` also
  has the version hard-coded in its HTML string — both must be updated
  together on every version bump (they can't share a Python variable because
  Gradio HTML is a string literal, not an expression).

- **Theme and CSS are set in `app.py`'s `launch()`**, not in `build_ui()`.
  Gradio 6 requires `css=` and `theme=` to be passed to `launch()`, not to
  `gr.Blocks()`.  `build_ui()` constructs the layout with a plain
  `gr.Blocks(title=...)` and no theme/css arguments.  This is intentional
  and consistent with how the prior phases left the launch block.

## See also

- ADR-0015 — Phase 1 (ui_assets.py extraction)
- ADR-0016 — Phase 2 (slurmcore.py extraction)
- ADR-0017 — Phase 3 (slurmio.py extraction)
- ADR-0001 — original "single file by design" rationale (now superseded by
  the four-phase modularisation)
- `slurm_ui.py` — the file created by this decision
