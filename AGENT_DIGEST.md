# AGENT_DIGEST.md — pre-computed code map for AI agents

> **You must read this file before doing anything else in this repo.**
> It saves you a full pass of `app.py` (~2 100 lines) on every session
> and tells you where load-bearing decisions live.

This digest is anchored on **identifier names** and **unique comment
markers**, not line numbers (which shift with edits). When you grep,
use the comment markers and identifier names listed here.

If you find yourself wanting to read source you don't see referenced
here, that's a sign this digest is stale — update it as part of your
PR.

---

## Project shape (one-liner)

Single-file Python app: a Gradio UI on top of a NumPy/SciPy/librosa
DSP pipeline that chops, time-stretches, and applies effects to
audio. Distributed as a code-signed, notarized macOS `.app` inside a
`.dmg`.

Current version: see `__version__` in `slurm_ui.py` and the matching
`<div class="slurm-tag">` in `build_ui()` (truth copy is `build.sh`'s `VERSION="0.1.3"`).

---

## File map

```
app.py                            ← bootstrap + imageio-ffmpeg wiring + __main__ launch
                                     (~199 lines after Phase-4 modularisation — ADR-0018)
slurm_ui.py                       ← Gradio UI: layout, event handlers, video export,
                                     process(), burn_fx(), render_video(), _quit_app(),
                                     build_ui() (ADR-0018)
ui_assets.py                      ← static browser content: INIT_JS, CUSTOM_CSS,
                                     base64 GIF Easter eggs, icon (ADR-0015)
slurmcore.py                      ← pure audio DSP: detect_slice_points, apply_envelope,
                                     slurmify, _fx_*, apply_fx (ADR-0016)
slurmio.py                        ← filesystem IO: _asset, load_audio, _write_audio,
                                     session-temp machinery (ADR-0017)
slurmify.spec                     ← PyInstaller spec
build.sh                          ← codesign + notarize + DMG
entitlements.plist                ← macOS hardened-runtime entitlements
requirements.txt                  ← Python deps (>=, no upper bound)
stubs/numba/__init__.py           ← passthrough numba shim (see ADR-0002)
assets/
    siena_dancer.gif              ← processing animation
    siebaSlurm_A003.mp4           ← 1.5 s 720p H.264 video loop (see ADR-0006)
    subvoyant_bug.png             ← legacy; kept on disk, no longer rendered
graphic/
    siebaSlurm_A003/              ← source PNGs for the loop (NOT bundled)
    siebaSlurm_A001.psd, *.aep    ← AE / Photoshop sources
icon/                             ← .icns + source PNGs

README.md                         ← user-facing setup
TECHNICAL.md                      ← comprehensive engineering reference
CLAUDE.md                         ← agent operating instructions
SLURMER_BETATEST_INSTRUCTIONS.md  ← release notes for testers
SLURMCORE_COMPARISON.md           ← long-form: how Slurmify differs from general slurmcore (also bundled in DMG)
LICENSE                           ← GPL-3.0 + third-party notices (also bundled in DMG)
AGENT_DIGEST.md                   ← THIS FILE
docs/adr/                         ← architecture decision records (0001-0018)
graphic/
    max.gif                       ← Max-the-tester face (hover gif on MAX RANDOM radio)
    hobermanmax.gif               ← Hoberman-Max (hover gif on 🎲 randomize all button)
    RGBOB.gif                     ← Bob (hover gif on 📁 reveal temp files button)
```

All four modularisation phases are complete.  The five-module architecture:

```
app.py       — bootstrap + launch           (Phase 4 — ADR-0018)
slurm_ui.py  — Gradio UI + handlers        (Phase 4 — ADR-0018)
ui_assets.py — static browser content      (Phase 1 — ADR-0015)
slurmcore.py — pure audio DSP              (Phase 2 — ADR-0016)
slurmio.py   — filesystem IO               (Phase 3 — ADR-0017)
```

---

## Section signposts inside `app.py` (grep these comments)

| Marker (unique substring) | File | What lives there |
|---|---|---|
| `# PyInstaller bundle bootstrap` | **app.py** | sys.frozen detection, bin/ PATH prepend, NUMBA_DISABLE_JIT |
| `# Wire up imageio-ffmpeg` | **app.py** | imageio-ffmpeg PATH + FFMPEG_BINARY env wiring |
| `# Application modules` | **app.py** | imports of slurmio, ui_assets, slurm_ui, gradio |
| `if __name__ == "__main__":` | **app.py** | `_fonts`, `_favicon_js` (ADR-0010), `_head`, `ui.launch(...)` |
| `# Asset path resolution` | **slurmio.py** | `_asset()` — dev vs. bundle path resolver |
| `# Session-scoped temporary directory` | **slurmio.py** | `SESSION_TMP_DIR`, `_new_temp_path`, `_reveal_temp_dir`, atexit + orphan sweep (ADR-0011) |
| `# Audio input` | **slurmio.py** | `SUPPORTED_EXTS`, `TARGET_SR`, `load_audio` |
| `# Audio output` | **slurmio.py** | `_SF_FORMATS`, `_FFMPEG_FORMATS`, `_write_audio` |
| `def detect_slice_points(` | **slurmcore.py** | beat-grid + transient-snap slice-point engine (MAX RANDOM trimodal — ADR-0012) |
| `def apply_envelope(` | **slurmcore.py** | per-slice fade-in/out (anti-click) |
| `def slurmify(` | **slurmcore.py** | main DSP pipeline (trim → stretch → slice → per-slice FX → concat → normalize); takes `(y, sr)` → returns `(ndarray, int)` — ADR-0016 |
| `# FX DSP helpers` | **slurmcore.py** | `_fx_distortion`, `_fx_ring_mod`, `_fx_delay`, `_fx_phaser` — pure numpy (no IO, no Gradio) |
| `def apply_fx(` | **slurmcore.py** | full FX chain (dist→ring→delay→phaser) — pure DSP, called by `burn_fx` in slurm_ui.py |
| `INIT_JS = """` | **ui_assets.py** | the multi-line browser-side JS string (~500 lines) |
| `// ── Skin switcher ──` | ui_assets.py | URL-param + localStorage skin selection (ADR-0007) |
| `// ── Web Audio FX chain ──` | ui_assets.py | FX state, `_fxWalk`, `_fxCurve`, `_fxApply`, `_fxSetup` |
| `// ── Audio-reactive viz loop` | ui_assets.py | rAF loop powering VU meter and acid halo |
| `// ── MAX RANDOM hover gif ──` | ui_assets.py | INIT_JS that tags the MAX RANDOM radio label with `.slurm-max-option` |
| `// ── Allow ANY file type on the audio input ──` | ui_assets.py | INIT_JS strip-`accept` (legacy; real fix for video is ADR-0009) |
| `CUSTOM_CSS = """` | **ui_assets.py** | the multi-line CSS string (default + acid + hardware skins) |
| `_MAX_GIF_B64 = "` | ui_assets.py | base64 Max hover gif + CSS (right-slide). Must precede the CSS += f-string that embeds it. |
| `_BOB_GIF_B64 = "` | ui_assets.py | base64 Bob hover gif + CSS (bottom-up spring). Must precede its CSS += f-string. |
| `_HOBERMAN_GIF_B64 = "` | ui_assets.py | base64 Hoberman-Max hover gif + CSS (bottom-up spring). Must precede its CSS += f-string. |
| `# ── Compact form controls` | ui_assets.py | radio chip rules, `.slurm-dropdown` (ADR-0014 §4), `.slurm-audio` |
| `__version__ = "` | **slurm_ui.py** | canonical version string — also hard-coded in the slurm-tag div in build_ui() |
| `_AUDIO_EXTS = frozenset` | **slurm_ui.py** | extensions routed straight to audio_in without ffmpeg extraction |
| `def burn_fx(` | **slurm_ui.py** | thin Gradio wrapper: validates path, loads with native SR, calls `apply_fx()`, writes output |
| `def render_video(` | **slurm_ui.py** | YouTube MP4 export — auto-burns FX if FX-burned-output selected without prior burn; ADR-0006 |
| `def _jumble_name(` | **slurm_ui.py** | filename-shuffle helper for the MP4 export |
| `def _leetify(` | **slurm_ui.py** | leet-substitution helper used by `_jumble_name` |
| `def process(` | **slurm_ui.py** | UI shim around `slurmify()` (validation, gr.Error wrapping) |
| `def _quit_app(` | **slurm_ui.py** | Quit button handler — uses `os._exit(0)` after a 0.8 s timer |
| `def build_ui(` | **slurm_ui.py** | the Gradio Blocks layout |
| `def _route_upload(` | **slurm_ui.py** | universal upload router — audio passes through, video → ffmpeg extract (ADR-0009) |
| `def _on_resolution_change(` | **slurm_ui.py** | auto-checks shuffle box on MAX RANDOM (ADR-0013) |
| `def _randomize_all(` | **slurm_ui.py** | 🎲 randomize all button — random slurm params (musical bias) |
| `def _reveal_temp_dir(` | **slurmio.py** | 📁 reveal temp files — opens SESSION_TMP_DIR in OS file browser |

---

## Load-bearing identifiers — never rename without checking everywhere

### Python globals / module-level

```
__version__              # lives in slurm_ui.py — MUST stay in sync with build.sh, slurmify.spec,
                         # AND the hard-coded version string in the slurm-tag div inside build_ui()
INIT_JS                  # the JS string (see ADR-0004)
CUSTOM_CSS               # the CSS string
_ICON_B64, _ICON_TAG     # base64'd Siena cat icon (header + favicon ADR-0010)
_MAX_GIF_B64             # base64 Max gif (MAX RANDOM hover, right-slide)
_BOB_GIF_B64             # base64 Bob gif (reveal-temp-files hover, bottom-up spring)
_HOBERMAN_GIF_B64        # base64 Hoberman-Max gif (randomize-all hover, bottom-up spring)
_LEET_PAIRS              # leet substitution table for _jumble_name (slurm_ui.py — ADR-0018)
# ── now in slurmio.py (ADR-0017) ──
_SF_FORMATS              # output formats handled by libsndfile
_FFMPEG_FORMATS          # output formats handled by ffmpeg branch
TARGET_SR = 44_100       # internal sample rate (don't change without hunting)
SUPPORTED_EXTS           # input file extension whitelist (audio + video containers)
SESSION_TMP_DIR          # per-process temp dir (ADR-0011) — auto-cleaned at exit
# ── in slurm_ui.py (ADR-0018) ──
_AUDIO_EXTS              # module-level frozenset in slurm_ui.py — extensions routed
                         # straight to audio_in without ffmpeg extraction by _route_upload
```

### Module-level helpers — now in `slurmio.py` (ADR-0017)

```
_asset(relative_path)           # resolve bundled asset path (dev vs. .app bundle)
_new_temp_path(suffix, prefix)  # the ONLY way to create temp files (ADR-0011)
load_audio(path)                # load any audio/video → (mono float32 ndarray, sr)
_write_audio(y, sr, fmt)        # write ndarray → session-scoped temp file
_cleanup_session_tmp()          # atexit handler
_sweep_orphan_session_dirs()    # startup orphan cleanup (crashed prior sessions)
_reveal_temp_dir()              # opens SESSION_TMP_DIR in Finder/Explorer/xdg-open
```

### JavaScript globals (top-level inside the IIFE)

```
_dbg(msg)                # console logger with [SLURM] / [slurm] prefix
_fxCtx                   # AudioContext (created in _fxSetup, idempotent — ADR-0003)
_fxSrc                   # MediaElementAudioSourceNode bound to #slurm-fx-audio
_fxN                     # the FX node graph: { dist, ringGain, delay, phaseAP, analyser, ... }
_fxP                     # FX slider state — slider js= callbacks mutate this
_fxLastSrc, _fxFirstFound # state for the src-mirroring polling loop
window.slurmFx           # exposed setters: setDist(v), setRingFreq(v), ...
window.slurmSetSkin      # exposed skin switcher callable
_SKIN_NAMES              # whitelist: ['default', 'acid', 'hardware']
```

### DOM IDs (referenced from CSS, JS, and Python — all three)

```
#slurm-audio-out         # gr.Audio output (slurm result) — Gradio component
#slurm-fx-audio          # dedicated <audio> for the FX preview (ADR-0003)
#slurm-fx-panel          # FX accordion (themed)
#slurm-video-panel       # video export accordion (themed)
#slurm-burn-btn          # primary FX-burn button (themed)
#slurm-video-btn         # primary video-render button (themed)
#slurm-clock-wrap        # playhead clock div (rAF-driven)
#slurm-in-btn, #slurm-out-btn, #slurm-clear-btn  # I/O time-mark buttons
#slurm-skin-picker       # <select> for skin choice (ADR-0007)
#slurm-vu-meter          # <canvas> driven by the analyser (hardware skin)
#slurm-go-halo           # <div> driven by the analyser (acid skin)
#siena-dancer            # processing animation gr.Image
#start-sec-box, #end-sec-box  # in/out time textboxes (matched info=, baseline-pinned)
#slurm-seed-box          # seed textbox (matched compact styling)
#slurm-util-bar          # row containing 🎲 randomize all + 📁 reveal temp files
#slurm-randomize-btn     # 🎲 randomize all button (Hoberman-Max hover via .slurm-max-popup)
#slurm-reveal-btn        # 📁 reveal temp files button (Bob hover via .slurm-bob-option)
#slurm-media-file        # universal upload gr.File (ADR-0009)
```

### CSS classes used as styling hooks (via `elem_classes=`)

```
.slurm-audio             # all gr.Audio components (input + output)
.slurm-audio-output      # output-only audio (slightly more compact)
.slurm-dropdown          # dark-themed dropdown (ADR-0014 §4)
.slurm-io-btn            # in/out + utility row buttons (compact transparent)
.slurm-io-clear          # the ✕ clear button (warning red on hover)
.slurm-max-option        # MAX RANDOM radio label (right-slide gif)
.slurm-max-popup         # randomize-all button (bottom-up Hoberman-Max gif)
.slurm-bob-option        # reveal-temp-files button (bottom-up Bob gif)
.slurm-media-file        # universal upload gr.File styling hook
.slurm-header-link       # the cat icon + SIENA SLURMER title (link to subvoyant.com)
```

---

## "Where do I add X?" recipes

### A new slurmify parameter

1. Add a `gr.Slider` / `gr.Checkbox` in `build_ui()` in the input column.
2. Add it to the `inputs=[...]` of the `go_btn.click(...).then(fn=process,...)` chain.
3. Add a parameter to `process()` and pass it through to `slurmify()`.
4. **Implement the DSP step inside `slurmify()` in `slurmcore.py`** (not app.py)
   at the right pipeline stage.
5. Update `_progress(...)` fractions if the new step is heavy (`slurmify()` reports
   trim/load 0.0 → stretch 0.15 → pitch 0.28 → slice points 0.40 → slicing 0.50 →
   per-slice 0.60-0.80 → mix 0.82 → done 1.0).
6. **If the parameter affects the slurm output and you want it preserved in
   the exported MP4**, add it to the `patch` dict in `render_video()`.

### A new FX

1. **JS preview chain (`_fxSetup` in `ui_assets.py`)** — create AudioNodes,
   connect into the chain in the right place, add state to `_fxP`.
   Update `_fxApply()` to push state into nodes. Expose setters on `window.slurmFx`.
2. **Python burn parity (`slurmcore.py`)** — implement `_fx_<name>(y, sr, ...)`
   that produces the same output as the JS graph. Add it to `apply_fx()` in
   `slurmcore.py` in the same chain order as the JS graph.
   The `burn_fx()` wrapper in `slurm_ui.py` passes parameters through to `apply_fx()`
   — add the new parameter to both `apply_fx()` in slurmcore AND `burn_fx()` in slurm_ui.py.
3. **UI** — sliders in the FX accordion. Mirror them to `window.slurmFx.set*`
   via `slider.change(fn=None, js=...)` (use the existing `_js = lambda fn: ...`
   helper).
4. **Pass parameters through `burn_btn.click(...)` inputs** so `burn_fx`
   gets them.
5. **Add to `patch.fx` in `render_video()`** so they're preserved in MP4
   metadata.

### A new keyboard shortcut

Add a `keydown` branch in `INIT_JS` (search for `_dbg('keydown listener attached'`).
Use `slurmFindBtn(id, text)` and click the result. Make sure the button has a
stable `elem_id`.

### A new output format

Add an entry to `_SF_FORMATS` (soundfile-direct) or `_FFMPEG_FORMATS` (needs
the ffmpeg encode branch) **in `slurmio.py`**. Add it to the `output_format`
`gr.Dropdown` in **`slurm_ui.py`** (inside `build_ui()`). No other changes —
`_write_audio` dispatches by name.

### A new skin

1. Add a CSS block scoped by `body[data-skin="newname"]` to `CUSTOM_CSS`,
   placed after the existing skin blocks.
2. Add `'newname'` to `_SKIN_NAMES` in `INIT_JS`.
3. Add a `<option value="newname">` to the `<select id="slurm-skin-picker">`
   in the header `gr.HTML`.

### A new dependency

1. Add to `requirements.txt` (`>=` constraint).
2. If it has dynamic imports (most things do): add to `hiddenimports` in
   `slurmify.spec`.
3. If it ships data files: `collect_data_files("name")` and add to `datas`.
4. Run `./build.sh`, launch the resulting `.app`, exercise the new code path.

### A new ADR

1. Pick the next number in `docs/adr/`.
2. Copy a recent ADR (e.g. `docs/adr/0011-session-scoped-temp-cleanup.md`) as a template.
3. Add it to the index in `docs/adr/README.md`.
4. Reference it from this digest if it touches a load-bearing identifier.

### A new hover-gif easter egg on a button

1. Encode the gif to base64. Save the constant near `_MAX_GIF_B64` /
   `_BOB_GIF_B64` / `_HOBERMAN_GIF_B64` (use a Python script via bash to
   avoid pasting 7+ KB of base64 through tool calls — see how it was done
   in v0.1.1).
2. Append a CSS block to CUSTOM_CSS (via `CUSTOM_CSS += f"""..."""`) that
   defines the new class. Existing patterns:
   - **Right-slide** (good for things on the left side of the layout):
     see `.slurm-max-option` (positioned via `left: calc(100% + 12px)`).
   - **Bottom-up spring** (good for buttons in horizontal rows): see
     `.slurm-bob-option` and `.slurm-max-popup` (`bottom: 0` + bouncy
     `cubic-bezier(0.34, 1.56, 0.64, 1)` transition).
3. Add `elem_classes=["existing-class", "slurm-yourname"]` to the target
   widget's Gradio definition. The `:hover::after` pseudo-element does the
   reveal — no JS needed unless you're tagging a label by text content
   (see `_slurmTagMaxRandom` for that pattern).

### A new utility button (with optional hover gif)

1. Add `gr.Button` to the `slurm-util-bar` row (or a new row). Use
   `elem_classes=["slurm-io-btn"]` for the compact transparent style.
2. Wire `btn.click(fn=..., inputs=..., outputs=...)` near the other event
   handlers in `build_ui()`.
3. (Optional) add a hover gif via the recipe above.

### A new place that creates temp files

1. Use `_new_temp_path(suffix=".ext", prefix="slurm_yourthing_")`.
   This is the ONLY way — direct `tempfile.mkstemp()` calls leak to
   the system tmpdir and won't be cleaned up at exit.
2. The fd is closed automatically; just write to the returned path.

---

## Critical danger zones (each has an ADR — read it before changing)

| Zone | ADR | One-line warning |
|---|---|---|
| `_fxSetup` idempotence | [0003](docs/adr/0003-createmediaelementsource-once.md) | `createMediaElementSource` is one-shot per element, **for the lifetime of that element**. Never rebind. |
| INIT_JS injection mechanism | [0004](docs/adr/0004-init-js-via-head.md) | Use `launch(head=...)`. `gr.Blocks(js=...)` and `<script>` in `gr.HTML` both break in Gradio 6. |
| PyInstaller `optimize=` | [0005](docs/adr/0005-pyinstaller-optimize-zero.md) | Must stay 0. Anything else hits "zlib header mismatch" on lazy-loaded modules. |
| Numba | [0002](docs/adr/0002-numba-stub-disable-jit.md) | Use the stub at `stubs/numba/`. Don't bundle real numba/llvmlite. |
| `_fxWalk` shadow-DOM recursion | [0003](docs/adr/0003-createmediaelementsource-once.md) | WaveSurfer's `<audio>` is in a shadow root. Plain `querySelectorAll('audio')` misses it. |
| Bundle path `Contents/Frameworks/` | (no ADR) | PyInstaller 6 on macOS puts everything here, not in `MacOS/`. `sys._MEIPASS` resolves to it. |
| Video export pipeline | [0006](docs/adr/0006-loop-mp4-stream-copy.md) | The loop is a pre-encoded MP4. `-c:v copy`. Don't reintroduce PNG sequences. |
| Skin system | [0007](docs/adr/0007-skin-system-data-skin.md) | Skin is `body.dataset.skin`. All skins share one CSS string. |
| MP4 metadata schema | [0008](docs/adr/0008-self-describing-mp4.md) | `description` ends with `PATCH={...JSON...}`. Don't break the schema without a `version` bump. |
| Universal upload routing | [0009](docs/adr/0009-universal-upload-gr-file.md) | `gr.Audio` rejects video MIME server-side. Use `gr.File(file_types=None)` + `_route_upload`. |
| Favicon mechanism | [0010](docs/adr/0010-favicon-via-js-injection.md) | `<link rel="icon">` in head AND `favicon_path` BOTH get overridden. JS injection w/ setTimeout retries is the only way. |
| Temp file cleanup | [0011](docs/adr/0011-session-scoped-temp-cleanup.md) | All temp files MUST go through `_new_temp_path()`. Otherwise they leak to system tmpdir forever. |
| MAX RANDOM distribution | [0012](docs/adr/0012-max-random-trimodal.md) | Trimodal (stutter/chop/held), NOT log-uniform. Bucket boundaries 5-30 / 100-500 / 1000-4000 ms — gaps are the design. |
| MAX RANDOM auto-shuffle | [0013](docs/adr/0013-auto-shuffle-max-random.md) | Selecting MAX RANDOM auto-checks shuffle box via `resolution.change()` handler. Don't internalize this in `slurmify()`. |
| Gradio quirks catalog | [0014](docs/adr/0014-gradio-quirks-collected.md) | First place to look when a Gradio component does something weird. Living document. |
| ui_assets.py GIF/CSS ordering | [0015](docs/adr/0015-modular-file-structure.md) | GIF b64 vars and CSS += blocks are interleaved on purpose — each GIF must be defined before the CSS f-string that embeds it. Do not reorder. |
| hiddenimports in slurmify.spec | [0015](docs/adr/0015-modular-file-structure.md) | Every new local module (ui_assets, slurmcore, …) MUST appear in hiddenimports or the .app crashes at startup. |
| slurmcore.py purity rule | [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | slurmcore.py must NEVER import os/sys/soundfile/gradio/shutil/subprocess. All file I/O is in slurmio.py; all UI is in slurm_ui.py. |
| slurmify() IO refactor | [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | slurmify() now takes `(y, sr, ...)` and returns `(ndarray, int)`. It does NOT load or write files. process() wraps it with load_audio + _write_audio. |
| apply_fx() / burn_fx() split | [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | apply_fx (slurmcore) = pure DSP. burn_fx (slurm_ui.py) = thin wrapper: validate path → load → apply_fx → write. |
| dual FX channel (JS + Python) | [0015](docs/adr/0015-modular-file-structure.md), [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | Every FX exists in both slurmcore.py AND INIT_JS (ui_assets.py). Adding/changing any FX parameter requires edits in BOTH places. |
| slurmio.py purity rule | [0017](docs/adr/0017-slurmio-filesystem-extraction.md) | slurmio.py must NEVER import gradio at the top level. One lazy `import gradio as _gr` inside `_reveal_temp_dir`'s except handler is the only allowed exception. |
| slurmio.py session-temp side effects | [0017](docs/adr/0017-slurmio-filesystem-extraction.md) | Importing slurmio runs `tempfile.mkdtemp()` and `atexit.register()` once. Test code that imports slurmio will create a temp dir — this is intentional and matches prior app.py behaviour. |
| slurm_ui.py purity rule | [0018](docs/adr/0018-slurm-ui-extraction.md) | slurm_ui.py must NEVER import from `app`. Allowed local imports: `slurmio`, `slurmcore`, `ui_assets` only. Importing `app` would create a circular dependency and crash the bundle. |

---

## Quick-run reference

```bash
# Dev run
source .venv/bin/activate
python app.py
# → http://127.0.0.1:7860
# Try skins via:  ?skin=acid  |  ?skin=hardware  |  ?skin=default

# Syntax check after edits (check ALL FIVE files — ADR-0015, ADR-0016, ADR-0017, ADR-0018)
python3 -c "import ast; ast.parse(open('app.py').read()); print('app.py OK')"
python3 -c "import ast; ast.parse(open('slurm_ui.py').read()); print('slurm_ui.py OK')"
python3 -c "import ast; ast.parse(open('ui_assets.py').read()); print('ui_assets.py OK')"
python3 -c "import ast; ast.parse(open('slurmcore.py').read()); print('slurmcore.py OK')"
python3 -c "import ast; ast.parse(open('slurmio.py').read()); print('slurmio.py OK')"

# Quick CSS brace check (CUSTOM_CSS lives in ui_assets.py now — ADR-0015)
python3 -c "
import sys; sys.path.insert(0, '.')
from ui_assets import CUSTOM_CSS
o, c = CUSTOM_CSS.count('{'), CUSTOM_CSS.count('}')
print(f'CUSTOM_CSS braces: {o} open / {c} close · {\"OK\" if o == c else \"MISMATCHED\"}')"

# Regenerate the loop MP4 from source PNGs (see ADR-0006)
ffmpeg -framerate 24 -i graphic/siebaSlurm_A003/siebaSlurm_A003_%05d.png \
       -vf "scale=1280:720:flags=lanczos,format=yuv420p" \
       -c:v libx264 -preset slow -crf 30 -movflags +faststart -an \
       assets/siebaSlurm_A003.mp4

# Full build (signed + notarized + DMG, 3–8 min)
./build.sh
```

---

## Version-bump checklist

When asked to bump to `X.Y.Z`, edit ALL of:

1. `build.sh` — `VERSION="X.Y.Z"`
2. `slurmify.spec` — both `CFBundleShortVersionString` and `CFBundleVersion`
3. `slurm_ui.py` — `__version__ = "X.Y.Z"` near the top of the module (ADR-0018)
4. `slurm_ui.py` — the hard-coded version string inside the `<div class="slurm-tag">` HTML in `build_ui()` (ADR-0018 — this can't share the Python variable because Gradio HTML is a string literal)
5. `SLURMER_BETATEST_INSTRUCTIONS.md` — title, install-step DMG filename, footer
6. `SLURMER_BETATEST_INSTRUCTIONS.md` — new "What's new in X.Y.Z" section at the top
7. `TECHNICAL.md` — last-updated stamp at the bottom

Then verify via `grep -rn "X\.Y\.(Z-1)" .` (excluding `.venv/`, `.git/`,
`build/`, `dist/`). The DMG filename auto-derives from `VERSION` in
`build.sh`; don't update it separately.

---

## Maintenance — when this digest is wrong

If you read this digest, then look at `app.py`, and find the section
markers don't exist or the identifiers don't match:

1. **Don't trust the digest.** Re-derive what you need from the code.
2. **Update the digest** as part of the same change.
3. **If the change is significant**, add an ADR. Most non-trivial
   churn deserves one.

The digest going stale is itself a signal worth noticing — it means
the codebase has drifted from a state that was previously well-mapped.

---

*Last updated: 2026-05-06 · v0.1.3 · Phase-4 modularisation complete (slurm_ui.py — ADR-0018)*
