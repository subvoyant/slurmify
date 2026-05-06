# ADR-0015: Modular file structure — extract ui_assets.py (Phase 1)

- **Status:** Accepted
- **Date:** 2026-05-06

## Context

`app.py` grew to ~3,600 lines as new features were added across v0.1.1–v0.1.3.
Roughly 50 % of those lines were pure static strings — browser JavaScript
(`INIT_JS`, ~500 lines) and CSS (`CUSTOM_CSS`, ~1,200 lines across five
concatenated blocks) — that do no Python work at all.  Editing either string
required scrolling past thousands of lines of unrelated audio DSP code, and
diffs that touched only the JS or CSS were hard to review.

CLAUDE.md originally stated "single file by design" to keep PyInstaller
analysis simple.  That rationale still holds for the audio engine and Gradio
wiring.  But static string constants are a different case: extracting them
carries essentially zero PyInstaller risk (one `hiddenimports` entry) and
zero behavioural risk (name references in app.py remain identical).

## Decision

**Extract all static browser content into `ui_assets.py`.**

`ui_assets.py` contains exactly these names (in definition order):

| Name | What it is |
|---|---|
| `INIT_JS` | ~500 lines of browser JS — Web Audio FX chain, slider sync, hover gifs, favicon, keyboard shortcuts |
| `CUSTOM_CSS` | ~1,200 lines of Gradio CSS — dark theme, chip-row radios, Easter egg `::after` rules |
| `_MAX_GIF_B64` | Base64 GIF for the Max hover Easter egg (MAX RANDOM radio) |
| `_BOB_GIF_B64` | Base64 GIF for the Bob hover Easter egg (reveal-temp-files button) |
| `_HOBERMAN_GIF_B64` | Base64 GIF for the Hoberman-Max hover Easter egg (🎲 randomise-all) |
| `_ICON_B64` | Base64 PNG of the Subvoyant cat icon (favicon + header logo) |
| `_ICON_TAG` | Pre-assembled `<a><img></a>` HTML for the clickable header |

`app.py` imports all seven names via a single block:

```python
from ui_assets import (
    INIT_JS, CUSTOM_CSS,
    _MAX_GIF_B64, _BOB_GIF_B64, _HOBERMAN_GIF_B64,
    _ICON_B64, _ICON_TAG,
)
```

`slurmify.spec` gains `"ui_assets"` in `hiddenimports`.

## Why the GIF vars and CSS blocks are interleaved in ui_assets.py

Three of the five `CUSTOM_CSS` blocks are f-strings that embed base64 GIF
data directly into CSS `background-image: url(...)` rules, e.g.:

```python
CUSTOM_CSS += f"""
.slurm-max-option::after {{
    background-image: url("data:image/gif;base64,{_MAX_GIF_B64}");
}}
"""
```

Python evaluates f-strings at assignment time, so each GIF variable must be
defined **before** the CSS block that references it.  The definition order in
`ui_assets.py` therefore mirrors the original order in `app.py` — do not
reorder the blocks without checking for f-string dependencies first.

## Target four-module architecture

This ADR documents Phase 1 of a planned four-module split.  The full target:

```
app.py        — bootstrap + launch (~20 lines)
ui_assets.py  — static browser content (DONE — this ADR)
slurmcore.py  — pure audio DSP (Phase 2: detect_slice_points, slurmify,
                apply_envelope, burn_fx, FX helper functions)
slurmio.py    — filesystem IO (Phase 3: load_audio, _write_audio,
                temp-file management, _asset path resolution)
slurm_ui.py   — Gradio orchestration (Phase 4: build_ui, process,
                render_video, _quit_app)
```

Dependency graph (all edges point downward — no cycles):

```
app.py → slurm_ui → slurmcore
                   → slurmio
                   → ui_assets
                   → gradio
```

## The dual FX channel constraint

Any future extraction of audio DSP code must respect this invariant: **every
FX effect is implemented twice**, once in Python (`slurmcore.burn_fx`) and
once in JavaScript (the Web Audio node graph in `INIT_JS`).  The two
implementations share nothing but the slider parameter values.

- **Python path**: `burn_fx()` runs at export time on the NumPy array.
- **JS path**: the Web Audio chain runs in the browser in real-time for
  zero-latency preview.

Adding a new FX parameter therefore requires edits in **both**
`slurmcore.py` (Phase 2 target) **and** `ui_assets.py`.  The parameter name,
range, and default must match so the preview sounds identical to the export.

## Consequences

**Wins**

- `app.py` drops from 3,569 lines to ~1,841 lines.
- INIT_JS and CUSTOM_CSS can be edited in their own file with proper JS/CSS
  syntax highlighting in any editor.
- Git diffs that change only the JS or CSS are no longer buried in a 3,500-
  line Python file.
- The structure documents a clear path to further modularisation.

**Costs / risks**

- One new `hiddenimports` entry in `slurmify.spec`.  If it were missing, the
  bundled `.app` would crash at startup with `ModuleNotFoundError: ui_assets`.
  This is an easy mistake; the entry is now present and must not be removed.
- The GIF-var / CSS-block interleaving in `ui_assets.py` looks unusual.  The
  reason is explained in both the file header and this ADR — read either one
  before reordering the blocks.

## See also

- ADR-0001 — original "single file by design" rationale
- ADR-0003 — `createMediaElementSource` once (affects INIT_JS)
- ADR-0004 — INIT_JS injection via `head=` (not `gr.Blocks(js=...)`)
- ADR-0014 — Gradio quirks catalog (governs CSS and JS authoring rules)
- `ui_assets.py` — the file created by this decision
