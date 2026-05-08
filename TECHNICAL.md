# Slurmify — Technical Documentation

This document is the authoritative engineering reference for the Subvoyant
SIENA Slurmer. It is written for two audiences in parallel:

- **Newcomer** — the *For newcomers* boxes explain the concepts and the
  shape of the code without assuming prior experience with audio DSP,
  Gradio, Web Audio, or PyInstaller.
- **Expert** — the *For experts* sections give signatures, invariants,
  performance characteristics, and the sharp edges that are not obvious
  from reading the code.

Read in order on the first pass; afterwards it works as a reference.

---

## Table of contents

1. [Project shape](#1-project-shape)
2. [Runtime architecture](#2-runtime-architecture)
3. [Bootstrap — running both as a script and as a frozen `.app`](#3-bootstrap)
4. [Audio engine — the slurm DSP pipeline](#4-audio-engine)
5. [Output formats and ffmpeg](#5-output-formats-and-ffmpeg)
6. [The FX chain — Web Audio preview & Python "burn" parity](#6-the-fx-chain)
7. [Gradio UI wiring](#7-gradio-ui-wiring)
8. [Embedded JavaScript (`INIT_JS`)](#8-embedded-javascript-init_js)
9. [Theme and CSS](#9-theme-and-css)
10. [The build pipeline — PyInstaller, signing, notarization, DMG](#10-the-build-pipeline)
11. [Debugging recipes](#11-debugging-recipes)
12. [Sharp edges and gotchas](#12-sharp-edges-and-gotchas)
13. [How to add things](#13-how-to-add-things)
14. [Version-bump checklist](#14-version-bump-checklist)
15. [Glossary](#15-glossary)

---

## 1. Project shape

### For newcomers

Slurmify is a **five-module Python application** that runs a small local
web server (Gradio) and opens a browser tab. The UI lets the user drop in
audio, slice it up, and apply effects. Everything happens on the user's
own machine — there is no cloud component.

A second, parallel program lives in the static-assets module: a chunk of
**JavaScript** (`INIT_JS`, a multi-line Python string) that runs in the
browser and handles real-time audio effects, keyboard shortcuts, and a
live playhead clock. We embed it because Gradio's frontend is the only
practical surface for running browser code in this app.

The repo also contains a build pipeline (`build.sh` + `slurmify.spec`)
that turns the Python modules into a signed, notarized macOS `.app` bundle
so we can distribute it as a `.dmg`.

**Five-module architecture** (as of v0.1.3, Phase 4 modularisation — ADR-0018):

| Module | Lines | Role |
|---|---|---|
| `app.py` | ~199 | Bootstrap, imageio-ffmpeg wiring, `__main__` launch |
| `slurm_ui.py` | ~1 320 | Gradio layout, all event handlers, video export |
| `ui_assets.py` | ~1 800 | `INIT_JS` (browser JS), `CUSTOM_CSS`, base64 media |
| `slurmcore.py` | ~600 | Pure audio DSP — NumPy arrays in/out, no I/O |
| `slurmio.py` | ~320 | Filesystem IO — load/write audio, session temp dir |

```
slurmify/
├── app.py                    ← bootstrap + __main__: tiny entry point (~199 lines)
├── slurm_ui.py               ← all Gradio UI: layout, event handlers, video export
├── ui_assets.py              ← INIT_JS, CUSTOM_CSS, base64 GIFs and icons
├── slurmcore.py              ← pure DSP: slurmify(), apply_fx(), _fx_* helpers
├── slurmio.py                ← filesystem IO: load_audio, _write_audio, temp dir
├── requirements.txt          ← Python dependencies
├── slurmify.spec             ← PyInstaller spec (how to freeze all five modules)
├── build.sh                  ← codesign + notarize + DMG packaging
├── entitlements.plist        ← macOS hardened-runtime entitlements
├── stubs/numba/__init__.py   ← shim so librosa imports work in the bundle
├── assets/siena_dancer.gif   ← processing animation (shown during slurmify run)
├── assets/siebaSlurm_A003.mp4 ← pre-encoded 1280×720 loop for video export (ADR-0006)
├── icon/                     ← .icns and source PNGs
├── graphic/                  ← hover-gif sources (max.gif, hobermanmax.gif, RGBOB.gif)
├── docs/adr/                 ← architecture decision records (0001–0018)
├── README.md                 ← user-facing setup
├── TECHNICAL.md              ← this file
├── CLAUDE.md                 ← orientation for AI agents
├── AGENT_DIGEST.md           ← pre-computed code map for agents (read this first)
└── SLURMER_BETATEST_INSTRUCTIONS.md  ← release notes for testers
```

### For experts

- The five-module split was done in four phases (ADR-0015 through
  ADR-0018). See [§17](#17-modularisation) for the full story.
- The DSP code (`slurmcore.py`) is pure NumPy/SciPy plus `pyrubberband`
  (a CLI wrapper around the `rubberband` binary). No audio plug-in
  framework abstraction sits between us and the math.
- Gradio is treated as **a thin presentation layer**, not a framework.
  `build_ui()` in `slurm_ui.py` is mostly declarative and could be
  swapped for any other web UI without touching `slurmify()` in
  `slurmcore.py` or the FX DSP functions.
- The boundary between Python and JavaScript runs through Gradio
  events with `fn=None, js=...`, plus a global `window.slurmFx` API for
  slider-to-effect calls.
- Import graph has no cycles:
  `app.py → slurm_ui → slurmio / slurmcore / ui_assets`
  Nothing imports from `app.py`.

---

## 2. Runtime architecture

### For newcomers

Three layers cooperate at runtime:

```
┌────────────────────────────────────────────────────────────┐
│  Browser                                                   │
│  ┌──────────────────────┐   ┌──────────────────────────┐   │
│  │ Gradio frontend      │   │ Slurmify INIT_JS         │   │
│  │ (Svelte + WaveSurfer)│   │ (Web Audio FX chain,     │   │
│  │                      │   │  keyboard shortcuts,     │   │
│  └──────────┬───────────┘   │  live playhead clock)    │   │
│             │ websocket     └──────────┬───────────────┘   │
└─────────────┼──────────────────────────┼───────────────────┘
              │                          │
┌─────────────▼──────────────────────────▼───────────────────┐
│  Python process (uvicorn + FastAPI under Gradio)           │
│  ┌───────────┐  ┌───────────────┐  ┌────────────────────┐  │
│  │ build_ui()│  │ process()     │  │ slurmify()         │  │
│  │ Gradio    │→ │ UI shim       │→ │ DSP pipeline:      │  │
│  │ Blocks    │  │ (validation,  │  │  load → trim →     │  │
│  └───────────┘  │  seed parsing)│  │  stretch → slice → │  │
│                 └───────────────┘  │  per-slice fx →    │  │
│                                    │  concat → write    │  │
│                 ┌───────────────┐  └────────────────────┘  │
│                 │ burn_fx()     │  ┌────────────────────┐  │
│                 │ FX render     │→ │ _fx_distortion etc │  │
│                 └───────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          ffmpeg      rubberband     soundfile
        (mp3/aac)    (time-stretch) (wav/flac/ogg/aiff)
```

When the user clicks **slurmify**, the browser sends a websocket
message to Gradio's Python server, which runs `process()` →
`slurmify()`, writes a temp file, and returns the file path. Gradio
serves that file back to the browser (URL like
`/gradio_api/file=/tmp/slurmify_xxxx.wav`), and the audio component
plays it.

The Web Audio FX preview is a separate path. It mirrors the same file
URL into a dedicated `<audio>` element in the FX panel and routes that
element's audio through a Web Audio graph in the browser. The Python
side never sees the FX preview audio.

When the user clicks **burn FX to file**, the same FX settings are
re-rendered in Python (`burn_fx()`) using NumPy implementations that
match the JavaScript graph's behaviour, and the result is written to
disk.

### For experts

- Frontend ↔ backend is Gradio's standard websocket-RPC. No custom
  protocol layer.
- `process()` is the only Python-side click handler that does heavy
  work; everything else is fast (button shortcuts, slider mirroring).
  This keeps the GIL out of the user's way during slurmify runs.
- Process model: single Python process, single uvicorn worker. We
  do not enable Gradio's queue (no `.queue()` call), so concurrent
  requests are serialised. Acceptable for a local desktop app.
- The two FX rendering implementations (Web Audio in JS,
  `_fx_distortion`/etc. in Python) are **intentionally redundant**.
  The JS path drives the live preview; the Python path bakes a file.
  They are kept algorithmically equivalent so what you preview is what
  you export. See [§6](#6-the-fx-chain).

---

## 3. Bootstrap

### For newcomers

The first 50-or-so lines of `app.py` run before any heavy library is
imported. They make sure the program works in two very different
environments:

1. **As a normal Python script** during development (`python app.py`).
2. **As a frozen `.app` bundle** distributed to users (where Python and
   all its dependencies are packaged inside the `.app`).

The bootstrap detects which mode it's in via `sys.frozen`, then:

- Adds the bundled `bin/` directory (containing `rubberband` and
  `ffmpeg`) to the `PATH` so the libraries that shell out to them
  work.
- Disables `numba`'s JIT compiler — `numba` cannot compile inside a
  frozen bundle because there's no writable build cache and no LLVM
  toolchain. We ship a stub package that pretends `numba` is there but
  does nothing.
- Wires in `imageio-ffmpeg`'s static `ffmpeg` binary so we don't depend
  on the user having Homebrew's ffmpeg.

### For experts

```python
if getattr(sys, "frozen", False):
    _bundle_dir = sys._MEIPASS
    os.environ["PATH"] = os.path.join(_bundle_dir, "bin") + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("NUMBA_DISABLE_JIT", "1")
```

- `sys._MEIPASS` is PyInstaller's runtime extraction directory. In a
  one-folder bundle it points at `Contents/Frameworks/` (PyInstaller 6
  on macOS), **not** `Contents/MacOS/`. The build script's `RB_BIN`
  path reflects this.
- `imageio_ffmpeg.get_ffmpeg_exe()` returns the path to a static
  ffmpeg shipped inside the `imageio-ffmpeg` wheel. We expose it via
  `FFMPEG_BINARY` and prepend its directory to `PATH` so
  `librosa.load()` (which goes through `audioread`) finds it.
- `_asset(relative_path)` is the canonical helper for resolving any
  bundled asset; use it instead of `__file__`-based paths.
- We swallow exceptions from the `imageio_ffmpeg` import so a missing
  install in dev still works against system ffmpeg.

**Invariant:** anything that touches `librosa.load()` or
`pyrubberband` must run *after* the bootstrap. That's why the heavy
imports (`gradio`, `librosa`, `pyrubberband`, `soundfile`) come below
the `_asset()` helper, not at the top of the file.

---

## 4. Audio engine

This is the heart of the app: turn an input file into a sliced,
stretched, glitched output file.

### For newcomers — the pipeline

```
input.mp3
   │
   ▼
load_audio()                  ← decode to mono float32 @ 44.1 kHz
   │
   ▼
trim to [start_sec, end_sec]  ← optional in/out range
   │
   ▼
time_stretch (rubberband)     ← if preserve_pitch, else linear resample
   │                            (resampling = chipmunk effect)
   ▼
pitch_shift (rubberband)      ← independent semitone shift (skipped if 0)
   │
   ▼
detect_slice_points()         ← grid + transient onsets
   │
   ▼
cut into slices               ← simple list of np.ndarray
   │
   ▼
for each slice:
    apply_envelope()          ← short fade in/out (anti-click)
    maybe reverse             ← random per-slice
    maybe stutter (×2/3/4)    ← random per-slice
   │
   ▼
shuffle slices?               ← optional global randomization
   │
   ▼
concatenate                   ← np.concatenate
   │
   ▼
soft normalize to -1 dBFS     ← peak / 0.891
   │
   ▼
_write_audio()                ← soundfile or ffmpeg → temp file
   │
   ▼
output.wav (or mp3/flac/etc.)
```

Concepts you'll meet:

- **Sample rate** — how many numbers per second describe the
  waveform. We force everything to 44.1 kHz internally so all the
  downstream code can assume one rate.
- **Onset / transient** — a sharp moment in the audio (a drum hit, a
  consonant). `librosa.onset.onset_detect` finds these; we use them to
  snap slice boundaries to musical events instead of arbitrary
  positions.
- **Time-stretch vs. resample** — if you double the playback rate of a
  sound, it gets twice as fast and twice as high (chipmunk).
  Time-stretching (rubberband) keeps the pitch the same while changing
  the speed.
- **Envelope** — a multiplier applied to the start/end of a slice so
  it fades up from 0 and back down to 0. Without it, hard cuts make
  audible clicks.

### For experts — function reference

```python
load_audio(path: str) -> tuple[np.ndarray, int]
```
- Returns `(y, sr)` where `y` is mono float32 in `[-1.0, 1.0]` and
  `sr == 44100`.
- Goes through `librosa.load(..., sr=44100, mono=True)`. Format
  routing is `audioread`'s problem; ffmpeg must be on PATH for
  mp3/aac/m4a. The bootstrap guarantees that.
- No streaming — entire file is loaded into RAM. Acceptable for the
  song-length input we expect.

```python
detect_slice_points(y, sr, resolution: str, transient_sensitivity: float) -> np.ndarray
```
- `resolution ∈ {"1/4", "1/8", "1/16", "1/32"}`. Maps to
  `subdivs ∈ {1, 2, 4, 8}`.
- Falls back to BPM 120 if `librosa.beat.beat_track` raises.
- Output is sample indices, sorted, monotonically increasing.
  Minimum slice length is clamped to 256 samples (~5.8 ms at 44.1 kHz)
  so per-slice operations don't blow up.
- Hybrid mode (`0 < transient_sensitivity < 1`) snaps each grid point
  to the nearest onset *within a window* whose width shrinks linearly
  with sensitivity. `transient_sensitivity == 1.0` returns onsets only
  (not snapped grid points).

```python
apply_envelope(slice_audio, sr, envelope_ms: float) -> np.ndarray
```
- Linear fade-in / fade-out at both ends.
- `envelope_ms == 0` → identity (this is the canonical clicky-slurm
  setting; do not change without explicit reason).
- Fade length is clamped to half the slice length to handle very
  short slices.

```python
slurmify(y, sr, speed, resolution, transient_sensitivity,
         envelope_ms, preserve_pitch, pitch_shift_semitones,
         randomize_order, reverse_chance, stutter_chance,
         stutter_skip_ms=0, stutter_max_reps=4, stutter_spread=0.0,
         start_sec=0, end_sec=0, bpm_override=None,
         seed=None, _progress=None) -> tuple[np.ndarray, int]
```

**Signature change (Phase 2 — ADR-0016):** `slurmify()` now lives in
`slurmcore.py`. It takes `(y, sr)` — a NumPy audio array and sample rate —
and returns `(ndarray, int)`. It does **not** load or write files. The
`process()` wrapper in `slurm_ui.py` handles loading with `load_audio()` and
writing with `_write_audio()` from `slurmio.py`.

- `_progress` is `gr.Progress()` (or any `callable(fraction, desc=str)`).
  Progress fractions: load 0.05 → stretch 0.15 → pitch 0.28 → slice
  points 0.40 → slicing 0.50 → per-slice 0.60–0.80 → mix 0.82 →
  encode 0.92 → done 1.0.
- Determinism: when `seed` is set we seed both `random` and `np.random`
  so reverse/stutter decisions and global shuffle replay identically.
  rubberband is **not** seeded; in practice it is deterministic for
  fixed inputs but if you ever rely on byte-identical outputs you must
  test that assumption.
- Soft normalize uses `0.891 ≈ 10^(-1/20)`, i.e. -1 dBFS, leaving 1 dB
  of headroom under clipping. Critical because stutter pile-ups can
  push peaks above unity.

**Stereo:** `slurmify()` is mono-only. `load_audio` collapses stereo to
mono. If you want stereo support you must change `load_audio`,
`detect_slice_points` (or the way it's called), the slice-cutting
loop, and `_write_audio`. The FX layer (`_fx_*` in §6) already handles
stereo because `burn_fx` is run on the *output* file independently.

---

## 5. Output formats and ffmpeg

### For newcomers

Some audio formats can be written directly by the `soundfile` library
(WAV, FLAC, OGG, AIFF). MP3 and AAC need the ffmpeg binary because
soundfile doesn't include those encoders. We write a temporary WAV
first, then call ffmpeg to transcode.

### For experts

```python
_SF_FORMATS      # wav, flac, ogg, aiff — single soundfile.write call
_FFMPEG_FORMATS  # mp3, aac (stored as .m4a) — wav-then-transcode
```

- `_write_audio(y, sr, fmt)` returns a path to a `slurmify_*` temp
  file. Caller does not need to clean up — `tempfile` cleans on
  process exit and Gradio rotates served files.
- The ffmpeg branch resolves the executable in this order:
  1. `shutil.which("ffmpeg")` — picks up `imageio-ffmpeg`'s binary
     because the bootstrap prepended its directory to PATH.
  2. `os.environ["FFMPEG_BINARY"]` — the bootstrap also sets this.
  3. The literal string `"ffmpeg"` (last-ditch).
- `subprocess.run(..., check=True, capture_output=True)`: stderr is
  swallowed unless ffmpeg fails. Add `text=True` and log if you need
  to debug encoding issues.
- Quality settings: MP3 uses `-q:a 2` (VBR ~190 kbps). AAC uses CBR
  192 kbps. Adjust `_FFMPEG_FORMATS` if you need higher fidelity.

---

## 6. The FX chain

This is the most subtle part of the codebase. Read carefully.

### For newcomers — the idea

The FX panel adds four classic effects on top of the slurmified
output: **distortion**, **ring modulation**, **delay**, and
**phaser**. Each has a few sliders.

There are **two** implementations of every effect:

1. **JavaScript / Web Audio API** runs *live* in the browser. As you
   drag a slider, the sound changes immediately. This is the "preview"
   pedalboard.
2. **Python / NumPy / SciPy** runs *offline* when you press "burn FX
   to file". It writes a new audio file with the effects baked in.

Both implementations are written to produce the same sonic result so
the preview matches the rendered file.

### For experts — Web Audio graph topology

Defined in `INIT_JS._fxSetup()`. Topology after setup, with `→` =
`AudioNode.connect(...)`:

```
audioEl ──MediaElementAudioSourceNode── _fxSrc
                                           │
                                           ▼
                                          dist (WaveShaper, oversample=2x)
                                           │
                                           ▼
                                          ringGain (Gain, base=1.0)
                                           ↑   (modulated by ringOsc → ringOscAmp → ringGain.gain)
                                           │
                                  ┌────────┴────────┐
                                  │                 │
                                  ▼                 ▼
                                delayDry      delay (feedback loop: delay → delayFb → delay)
                                  │                 │
                                  │                 ▼
                                  │              delayWet
                                  └────────┬────────┘
                                           ▼
                                       delayOut
                                           │
                                  ┌────────┴────────┐
                                  ▼                 ▼
                               phaseDry       phaseAP[0] → phaseAP[1] → phaseAP[2] → phaseAP[3]
                                  │                 │
                                  │                 ▼
                                  │              phaseWet
                                  └────────┬────────┘
                                           ▼
                                  _fxCtx.destination
```

State held in `_fxP` (a JS object) is the source of truth for slider
positions. `_fxApply()` reads `_fxP` and writes to the live graph
nodes. Slider `change` events on the Python side fire JS via
`window.slurmFx.set*(v)`, which mutates `_fxP` and calls `_fxApply()`.
**No Python round-trip.**

#### Critical invariants

**Invariant 1: `createMediaElementSource` may be called at most once
per `<audio>` element for the lifetime of that element.** The W3C
spec is explicit; `InvalidStateError` is thrown otherwise, and
*closing the AudioContext does not release the binding*. This is why
`_fxSetup` is idempotent: `if (_fxCtx) return;` early-returns on every
call after the first, and the chain is bound to a dedicated
`<audio id="slurm-fx-audio">` we own (declared inside the FX panel),
not to Gradio's WaveSurfer-managed element.

**Invariant 2: `AudioContext` is created suspended.** Browsers (Chrome,
Safari) refuse to start audio output until a real user gesture
happens. We therefore call `_fxSetup` from a `play` event listener
attached to the preview element — that listener runs *during* a user
gesture and so `_fxCtx.resume()` succeeds in the same tick.

**Invariant 3: src mirroring is independent of chain binding.** Two
mechanisms feed the slurm output URL into `#slurm-fx-audio`:
1. A `setInterval` in INIT_JS walks `#slurm-audio-out` (the Gradio
   audio component) and any nested shadow roots looking for an
   `<audio>` with a populated `src`/`currentSrc`/`<source>.src`,
   then sets `fxAudio.src = url`.
2. `audio_out.change(fn=None, js=...)` fires when Gradio's value
   changes; the JS reads the FileData and sets the same URL.

Both are kept because `gr.Audio.change` timing under WaveSurfer can
race with mount, and the polling loop is cheap (400 ms tick, two
DOM lookups). If both fail the user sees `0:00 / 0:00` — diagnostic
`console.log` lines starting with `[slurm]` cover every branch.

#### Python parity functions (`burn_fx`)

```python
_fx_distortion(y, drive)               → tanh(y*k)/tanh(k), k = 1+29*drive
_fx_ring_mod(y, sr, freq, depth)       → y * (1 + depth*sin(2πf t))
_fx_delay(y, sr, t, fb, mix)           → sample-by-sample feedback delay
_fx_phaser(y, sr, rate, depth)         → 4-stage allpass, LFO-modulated
```

Notes:

- **Distortion:** matches JS `_fxCurve(drive)` exactly: `k = 1 + 29*drive`,
  output normalised by `tanh(k)` so unity gain at peak input.
- **Ring mod:** matches JS topology of `gain.value=1` plus
  `oscOutput*depth` summed into `gain.gain`. Equivalent to
  `y * (1 + depth*sin(2πft))`. Stereo broadcast via `np.newaxis`.
- **Delay:** sample-accurate Python loop — slow but predictable. Uses
  a circular write index. JS uses a `DelayNode` + feedback loop; both
  are tape-style delay lines. **Performance:** the Python `_fx_delay`
  is `O(n_samples * n_channels)` with an interpreted loop; for a
  3-minute stereo file (~15.8 M samples) it takes ~3-5 s. Candidate
  for vectorisation if it becomes a bottleneck.
- **Phaser:** the JS implementation uses 4 cascaded allpass biquads
  with their `frequency` AudioParam continuously modulated by a sine
  LFO. The Python version takes a simpler approach — it uses the LFO
  *mean* to set a static centre frequency per stage and runs
  `scipy.signal.lfilter` once. **This is an intentional approximation**;
  the JS version sweeps, the Python version doesn't. The audible
  difference is mostly in the depth of the swirl. If you care about
  bit-perfect parity, replace this with a per-sample loop (slow).

`burn_fx` chains all four in order: dist → ring → delay → phaser, then
peak-normalises and clips to `[-1, 1]`. Order matches the JS graph.

---

## 7. Gradio UI wiring

### For newcomers

Gradio gives you Python-side widgets (sliders, dropdowns, audio
players, buttons) and renders them as a single web page. You declare
what should happen when a button is clicked or a slider changes
(`btn.click(fn=..., inputs=..., outputs=...)`), and Gradio handles
all the websocket plumbing.

`build_ui()` in `slurm_ui.py` is one big nested `with` block that builds
the whole layout. The UI is divided into:

- A header (icon + title + version tag)
- The input column: file upload, in/out time markers, knobs
- The dancer (a loading GIF that appears during processing)
- The slurmify output (`audio_out`)
- The `⚡ real-time FX` accordion: sliders + the FX preview audio +
  burn button + burn output

The actual rendering happens in `ui.launch(...)` in `app.py`'s `__main__`
block (CSS, JS, and theme are all passed there — not to `gr.Blocks()`).

### For experts — wiring rules

**Click chain pattern for `slurmify`:**

```python
go_btn.click(
    fn=lambda: gr.Image(visible=True),  # show dancer
    inputs=[],
    outputs=dancer,
).then(
    fn=process,                          # heavy work
    inputs=[audio_in, speed, ...],
    outputs=audio_out,
).then(
    fn=lambda: gr.Image(visible=False),  # hide dancer
    inputs=[],
    outputs=dancer,
)
```

`.then()` chains run sequentially regardless of success/failure of the
prior step. If `process()` raises a `gr.Error` the dancer-hide step
still runs.

**JS-only callbacks (`fn=None, js=...`):**

```python
btn.click(fn=None, inputs=[...], outputs=[...], js="(a, b) => [...]")
```

Rules:

1. The JS expression must be a **single callable function expression**
   (`"(...) => {...}"` or `"function(...){...}"`). Bare statements or
   IIFEs (`(function(){...})()`) will silently break the page.
2. Argument count = `inputs` length. Return value = array of
   `outputs` length, or empty array / `undefined` for `outputs=[]`.
3. The component value passed in is *the frontend value*. For
   `gr.Audio(type="filepath")` this is a `FileData` object with
   `path`, `url`, `mime_type`, `orig_name`, `meta`. **Do not assume**
   it is a string — handle the dict.

**Slider FX wiring:**

```python
_js = lambda fn: f"(v) => {{ window.slurmFx && window.slurmFx.{fn}(v); }}"
fx_dist.change(fn=None, inputs=[fx_dist], outputs=[], js=_js("setDist"))
```

The `change` event fires on every slider drag. `window.slurmFx` is
defined in `INIT_JS` once the FX chain is bound.

**`elem_id` is load-bearing.** Several IDs are referenced from
`INIT_JS` and CSS:

- `#slurm-audio-out` — the slurm output audio component (read by FX
  src polling, by the playhead clock, by the in/out probe).
- `#slurm-fx-audio` — the dedicated FX preview `<audio>` element
  (declared in a `gr.HTML` block inside the FX accordion).
- `#slurm-in-btn`, `#slurm-out-btn`, `#slurm-clear-btn` — the I/O
  shortcut buttons (clicked by the I and O keyboard shortcuts).
- `#slurm-clock-wrap` — the playhead clock div.
- `#slurm-fx-panel`, `#slurm-burn-btn` — themed via CSS.

**Gradio version pin.** `requirements.txt` says `gradio>=5.0`; we ship
6.14 in the bundle. Gradio 6 made several changes that affect us:
- `elem_id` is applied directly to the `<button>` element (not a
  wrapper) — `INIT_JS.slurmFindBtn` accommodates both forms.
- `gr.Blocks(js=...)` and `launch(js=...)` use `eval()` and break on
  IIFEs in some versions; we inject via `head=` instead (see
  [§8](#8-embedded-javascript-init_js)).
- `gr.Audio` uses WaveSurfer 7 with custom transport controls; the
  underlying `<audio>` element lives inside a shadow root.

---

## 8. Embedded JavaScript (`INIT_JS`)

### For newcomers

`INIT_JS` is a long Python triple-quoted string holding our
browser-side JavaScript. We inject it into the page's `<head>` via
`ui.launch(head="<script>...</script>")`. It runs once on page load
and sets up all the things Gradio doesn't do for us:

- A live playhead clock (the `► 0:00.00` you see while audio plays).
- Keyboard shortcuts (`I` = mark in, `O` = mark out).
- The Web Audio FX chain (distortion / ring mod / delay / phaser).
- The polling loop that mirrors Gradio's audio output URL into the
  FX preview element.
- A debug logger (`_dbg`) that writes to `console.log` with a
  `[SLURM]` prefix — open the browser DevTools to read it.

### For experts — module map

```
INIT_JS = (function () {
    _dbg(...)                         // console.log helper
    tick()                            // requestAnimationFrame clock loop
    keydown listener                  // I/O shortcuts → click slurm-in/out-btn
    _fxP                              // FX state (slider values)
    _fxWalk(root)                     // recursively walk shadow DOM for <audio>
    _fxCurve(drive)                   // tanh waveshaper curve
    _fxApply()                        // _fxP → live AudioNode params
    _fxSetup(audioEl)                 // build & connect the FX graph (idempotent)
    _fxSrcUrl(audioEl)                // try every possible src field
    setInterval(... 400ms ...)        // mirror Gradio src into #slurm-fx-audio
    setInterval(... 200ms ...)        // bind 'play' listener on first mount
    window.slurmFx                    // exposed setters for slider js= callbacks
    setTimeout(... 1000ms ...)        // post-mount DOM probe (debug)
})();
```

Important wiring details:

- The clock loop uses `requestAnimationFrame`, not `setInterval`.
  Pauses while the tab is backgrounded. Don't lower this to a wall-
  clock timer.
- `_fxWalk` is recursive over `el.shadowRoot`. WaveSurfer 7 places the
  `<audio>` element inside its own shadow root; ordinary
  `querySelectorAll('audio')` does not cross shadow boundaries.
- `_fxSrcUrl` tries `src`, `currentSrc`, `getAttribute('src')`, and
  finally `<source>.src`. Different Gradio versions / WaveSurfer
  modes populate different ones.
- The FX preview `<audio>` element (`#slurm-fx-audio`) is declared in
  a `gr.HTML` block inside the FX accordion. The polling loop refuses
  to operate until that element exists in the DOM.
- The chain binds on `play` rather than on first src observation
  because the `play` event is a real user gesture and so
  `_fxCtx.resume()` is allowed to actually transition the context to
  `running` state.

**Why we inject via `head=` instead of `gr.Blocks(js=...)`:**
Gradio 6's `js=` parameter uses `eval()`. It tolerates a single arrow
function expression but breaks on `(function(){...})();` IIFEs in
some patch releases. `head=` injects the script tag verbatim into
`<head>`, so the browser parses and runs it the normal way. This is
the only reliable injection point as of Gradio 6.14.

---

## 9. Theme and CSS

### For newcomers

`CUSTOM_CSS` (also a multi-line Python string) defines the dark
"Subvoyant" look — black background, cyan accent, orange highlights
on the active waveform region. We pass it to `ui.launch(css=...)`.

### For experts

- The theme is built on top of `gr.themes.Base(primary_hue="cyan",
  neutral_hue="slate")`. Gradio's CSS variables (`--body-text-color`,
  `--block-label-text-color`, etc.) are overridden with `!important`
  inside `:root`.
- Selectors inside `.gradio-container` are fragile across Gradio
  releases. If a selector stops matching after a Gradio bump:
  1. Reload with DevTools open and inspect the affected element.
  2. Check whether `data-testid` or class names changed.
  3. Prefer `elem_id` + `elem_classes` over deeper CSS selectors when
     adding new styled controls.
- The Subvoyant icon is bundled as a base64 PNG (`_ICON_B64`) directly
  in `app.py` so the header renders without any file IO. It is
  included in every release; replace via `_ICON_TAG` if rebranding.
- The Siena dancer is a separate GIF (`assets/siena_dancer.gif`)
  referenced via the `_asset()` helper.

---

## 10. The build pipeline

### For newcomers

To distribute Slurmify we need to give users a single thing they can
double-click. On macOS that's a `.app` bundle inside a `.dmg` disk
image, signed with our Apple Developer ID and notarized by Apple so
Gatekeeper doesn't flag it.

The build is two stages:

1. **PyInstaller** (`slurmify.spec`) takes `app.py` and bundles a
   complete Python interpreter + all dependencies + native binaries
   into a `.app` directory.
2. **`build.sh`** patches dylib paths, code-signs everything inside
   the bundle, sends it to Apple for notarization, staples the
   notarization ticket, and packages the result into a `.dmg`.

Run `./build.sh` from inside the venv. End-to-end takes 3–8 minutes,
mostly waiting for Apple's notarization service.

### For experts — `slurmify.spec`

```
collect_all("gradio")          → datas (templates/assets), bins, hidden imports
collect_all("gradio_client")   → same for the client
collect_all("safehttpx")       → reads version.txt at runtime
collect_all("groovy")          → reads version.txt at runtime
collect_data_files("librosa")  → cached data tables, example files
```

- `binaries=[(rubberband_bin, "bin"), (ffmpeg_bin, "bin"), ...]`
  copies the resolved binary paths into the bundle's `bin/`
  subdirectory. The bootstrap prepends that to PATH.
- `hiddenimports` is a long list because PyInstaller's static analysis
  misses dynamic imports in `librosa`, `uvicorn`, `pydantic`, etc.
  Don't trim this list speculatively — it took several iterations to
  get right.
- `pathex=["stubs"]` makes the numba stub visible to PyInstaller's
  scanner. Combined with `excludes=["llvmlite"]`, this gives librosa
  a working "numba" import without the multi-hundred-MB LLVM backend.
- `optimize=0` is mandatory. PyInstaller's `optimize=2` strips
  docstrings *and* writes optimised bytecode that fails to load some
  lazy-imported modules with a "zlib header mismatch" error. Do not
  flip this on without exhaustive smoke-testing.
- `console=False` removes the terminal window. Gradio's local URL
  printout is hidden, but `inbrowser=True` opens a browser tab
  automatically, so the user never needs to see it.
- `target_arch=None` inherits the host arch. Build on Apple Silicon
  for arm64; build on Intel for x86_64. We do not build universal
  binaries — keep one DMG per architecture if you ship to both.

### For experts — `build.sh`

Pipeline order matters. Each step depends on the previous one
producing exactly the artefact it expects.

1. **Pre-flight checks** — fail fast if `pyinstaller`, `rubberband`,
   or `imageio_ffmpeg` are missing.
2. **Clean** — `rm -rf build dist rw.*.dmg`. PyInstaller caches
   aggressively; without a full wipe `app.py` edits sometimes don't
   make it into the bundle.
3. **PyInstaller** — `pyinstaller slurmify.spec --noconfirm`.
4. **Fix rubberband dylib paths.** The Homebrew rubberband binary
   links against `/opt/homebrew/lib/librubberband.x.dylib` etc.
   Inside the bundle those paths don't exist. We:
   - Read every non-system dylib it links via `otool -L`.
   - Copy each into `Contents/Frameworks/`.
   - Rewrite the references with `install_name_tool -change OLD
     @loader_path/../NAME`. `@loader_path` is the directory of the
     binary doing the loading, so `@loader_path/..` resolves to
     `Contents/Frameworks/` — exactly where we copied the dylibs.
   - This is required *before* signing, because signing freezes the
     binary's contents.
5. **Codesign — inside-out.**
   - Resolve a "Developer ID Application" identity from the keychain.
   - Sign every `.dylib` and `.so` inside the bundle.
   - Sign vendored CLI binaries (`bin/rubberband`, `bin/ffmpeg`).
   - Sign the `.app` itself with `--deep` to catch anything missed.
   - Hardened runtime is mandatory for notarization
     (`--options runtime`) and requires the entitlements in
     `entitlements.plist`.
6. **Notarize** with `notarytool submit --wait`. `APPLE_ID` and
   `APP_PASSWORD` (an app-specific password from
   appleid.apple.com → Security) must be set near the top of the
   script. The team ID is your developer team identifier.
7. **Staple** the notarization ticket so Gatekeeper accepts the app
   offline.
8. **Create DMG** with `hdiutil` (UDZO compression). We deliberately
   skip `create-dmg` because it scripts Finder and is unreliable in
   automation.
9. **Codesign the DMG** — required for the download to be trusted on
   first launch.

**Entitlements** (`entitlements.plist`):

| Entitlement | Why |
|---|---|
| `cs.allow-unsigned-executable-memory` | numpy / soundfile / pydantic-core have JIT-like patterns under hardened runtime |
| `cs.disable-library-validation` | Allows loading the bundled rubberband/ffmpeg dylibs without per-dylib signing |
| `network.server` | Gradio binds to 127.0.0.1:7860 |
| `network.client` | Outgoing HTTP for any remote calls (currently none) |

**To rebuild without changing source:** `./build.sh` is idempotent
with a clean-tree assumption; the first step is a full `rm -rf`. If
you only changed `app.py`, the entire pipeline still re-runs but
that's by design.

---

## 11. Debugging recipes

### Browser-side issues

Open the developer console (Cmd+Opt+J in Chrome/Edge, Cmd+Opt+I in
Safari). Filter messages by `[SLURM]` or `[slurm]` for our own logs.

**FX preview shows `0:00 / 0:00`:** check the console for these
specific lines:

| Log line | What it means |
|---|---|
| (none) | INIT_JS hasn't run — verify `head=_head` is set in `ui.launch`. |
| `INIT_JS fired ✓` | INIT_JS ran. |
| `FX: preview element mounted, will bind chain on first play` | `#slurm-fx-audio` is in the DOM. |
| `FX: first audio src observed: ...` | The polling loop found a populated `<audio>` element inside `#slurm-audio-out`. |
| `FX: mirroring src into preview element: ...` | Set `fxAudio.src`. |
| `audio_out.change payload: {url:...}` | Gradio's change event fired. Inspect the object shape if extraction failed. |
| `FX: first play on preview element — binding chain` | User pressed play. Next line should be `FX chain ready, sr=44100`. |

If `first audio src observed` never fires, Gradio's audio element is
not exposing its `src` through any of the four fields `_fxSrcUrl`
checks. Add another fallback (e.g. `audioEl.dataset.src`) and a
`console.log(audioEl)` to inspect it.

If the chain binds but you hear nothing, check `_fxCtx.state` in the
console: `getCtx()` is not exposed but you can inspect via
`$0.AudioContext` after selecting the element. State should be
`running`. If `suspended`, the resume on play didn't take — verify
the `play` event listener is attached.

### Server-side issues

Run `python app.py` in a terminal (not from the bundle) and watch
stderr.

**"No module named X" inside the bundle, but works in dev:** add `X` to
`hiddenimports` in `slurmify.spec`. PyInstaller's static analysis
missed it.

**"Could not load mp3":** ffmpeg isn't on PATH. In dev, `brew install
ffmpeg`. In bundle, check that `imageio_ffmpeg.get_ffmpeg_exe()`
returns a valid path and the bootstrap actually prepended its
directory.

**"Failed to find Rubber Band Library":** dylib paths weren't fixed.
Re-run `build.sh`. Look at `otool -L
"dist/Subvoyant SIENA Slurmer.app/Contents/Frameworks/bin/rubberband"`
and verify all non-system references are `@loader_path/...`.

**"This program is damaged" on first launch on a tester's machine:**
notarization staple failed or DMG isn't signed. Check
`xcrun stapler validate` output during build, and confirm step 8
(DMG signing) ran.

### Audio-quality issues

**Output clips:** stutter chance is high and sliced peaks are piling
up before normalization. Either lower stutter chance or strengthen
the soft-normalize ceiling (currently `0.891 = -1 dBFS`).

**FX preview ≠ burned file:** check that the JS effect parameters
match the corresponding `_fx_*` Python implementations. The phaser
intentionally diverges (see [§6](#6-the-fx-chain)); the others should
sound very close.

**Burn FX errors with "Run slurmify first":** `audio_out` is empty.
The user clicked burn before producing slurm output. This is the
intended guard.

---

## 12. Sharp edges and gotchas

A non-exhaustive list of things that will bite you if you forget them.

1. **`createMediaElementSource` is one-shot per element.** The chain
   binds to a dedicated element we own. Never rebind. See [§6](#6-the-fx-chain).
2. **AudioContext autoplay policy.** Resume must happen during a user
   gesture (the `play` event qualifies; `setInterval` does not).
3. **PyInstaller bundle path is `Contents/Frameworks/`** (not `MacOS/`)
   on macOS, since PyInstaller 6. `sys._MEIPASS` resolves there too.
4. **`optimize=0` in the spec is mandatory.** Bytecode optimisation
   breaks lazy-loaded modules.
5. **numba is shimmed.** The real numba and llvmlite are deliberately
   excluded; `stubs/numba/` provides pass-through `@jit`/`@njit`
   decorators. `NUMBA_DISABLE_JIT=1` is set in the bootstrap.
6. **WaveSurfer's `<audio>` element lives in a shadow root.**
   `document.querySelector('audio')` misses it. Use `_fxWalk`.
7. **`fn=None, js=...` JS string MUST be a single function
   expression.** No bare statements, no IIFEs.
8. **Gradio's `js=` callback receives FileData, not a string,** for
   `gr.Audio(type="filepath")`. Handle `.url`, `.path`, and
   string-fallback branches.
9. **Codesigning order is inside-out.** Sign nested dylibs and
   binaries before the `.app`.
10. **Don't trim `hiddenimports` speculatively.** Add to it; remove
    only with full smoke-test.
11. **Determinism:** `seed` covers Python's `random` and `numpy.random`,
    not rubberband. Don't depend on byte-identical output across
    rubberband upgrades.
12. **`librosa.load` is mono-only as we use it.** Stereo input is
    collapsed at load. The FX chain handles stereo because it runs on
    the *output* file via `librosa.load(..., mono=False)` in
    `burn_fx`.
13. **`gr.Error` is the only exception that surfaces a friendly
    toast.** Wrap user-facing failures with it; everything else hits
    the red error box.
14. **Quit button uses `os._exit(0)` after a 0.8 s timer.** `sys.exit`
    doesn't work cleanly under uvicorn workers. The timer lets Gradio
    flush its response.

---

## 13. How to add things

### A new slurmify parameter (e.g. low-pass filter)

1. Add a `gr.Slider`/`gr.Checkbox` inside `build_ui()` in **`slurm_ui.py`**,
   in the input column.
2. Add it to the `inputs=[...]` of the `process` click chain (also in
   `build_ui()`).
3. Add a parameter to `process()` in `slurm_ui.py` and pass it through to
   `slurmify()`.
4. Implement the DSP step inside `slurmify()` in **`slurmcore.py`** at the
   appropriate pipeline stage. Do NOT add DSP code to `slurm_ui.py`.
5. Update `_progress` fractions in `slurmify()` if the new step is heavy.

### A new FX

1. **JS preview** (`ui_assets.py` — inside `INIT_JS`): in `_fxSetup`,
   create the new AudioNodes, connect them into the chain in the right
   place, and add their state to `_fxP`. Update `_fxApply()` to push
   state into nodes. Expose setters on `window.slurmFx`.
2. **Python burn parity** (`slurmcore.py`): add `_fx_<name>(y, sr, ...)`
   that produces the same output as the JS graph for matching parameters.
   Add it to `apply_fx()` in the same chain order as the JS graph.
3. **UI** (`slurm_ui.py`): add sliders to the FX accordion in `build_ui()`
   and a `change` handler that calls the new `slurmFx.set*` setter.
4. **Pass parameters through `burn_btn.click`** in `inputs=[..., your_slider]`
   (in `build_ui()`), then accept them as the matching positional parameter
   in `burn_fx()` in `slurm_ui.py`, and pass them to `apply_fx()` in
   `slurmcore.py`.

### A new keyboard shortcut

Add a `keydown` branch in `INIT_JS` that calls `slurmFindBtn(id, text)`
and clicks the resulting button. Make sure the button has a stable
`elem_id`.

### A new dependency

1. Add to `requirements.txt` (`>=` constraint).
2. If it has any C extensions or dynamic imports, add to
   `hiddenimports` in `slurmify.spec`.
3. If it ships data files, use `collect_data_files("name")` and add to
   `datas`.
4. Smoke-test by running `./build.sh` and launching the resulting
   `.app` from a clean machine state (or at least without the venv
   active).

### A new output format

1. Add an entry to `_SF_FORMATS` (if soundfile supports it directly)
   or `_FFMPEG_FORMATS` (if it needs ffmpeg).
2. Add it to the `gr.Dropdown` in the UI.
3. No other changes are required — `_write_audio` dispatches by name.

---

## 14. Version-bump checklist

Ten places carry the version string. All must move together.

| File | What to change |
|---|---|
| `build.sh` | `VERSION="X.Y.Z"` |
| `slurmify.spec` | `CFBundleShortVersionString` and `CFBundleVersion` (two keys) |
| `slurm_ui.py` | `__version__ = "X.Y.Z"` near the top of the module |
| `slurm_ui.py` | Hard-coded version string in the `<div class="slurm-tag">` HTML inside `build_ui()` (cannot share the Python variable — Gradio HTML is a string literal) |
| `SLURMER_BETATEST_INSTRUCTIONS.md` | Title (line 1), DMG filename in the install step, footer |
| `SLURMER_BETATEST_INSTRUCTIONS.md` | New "What's new in X.Y.Z" section at the top |
| `TECHNICAL.md` | Last-updated stamp at the bottom |
| `AGENT_DIGEST.md` | Last-updated stamp at the bottom + "Current version" near the top |
| `SLURMCORE_COMPARISON.md` | Version stamp in the footer |
| `docs/adr/0008-self-describing-mp4.md` | Example version field in the JSON sample (illustrative) |

After bumping, verify no stale references remain:

```bash
grep -rn 'X\.Y\.(Z-1)' --include='*.py' --include='*.sh' \
    --include='*.spec' --include='*.md' . \
    | grep -v '/.venv/' | grep -v '/build/' | grep -v '/dist/'
```

The only acceptable remaining matches are historical "What's new" entries
in `SLURMER_BETATEST_INSTRUCTIONS.md`. The DMG filename is auto-derived
from `VERSION` in `build.sh` — don't update it separately.

---

## 15. Glossary

| Term | Plain-English meaning |
|---|---|
| **Sample** | One number representing audio amplitude at one instant. |
| **Sample rate** | How many samples per second. We use 44,100. |
| **Mono / stereo** | One channel vs. two. We work in mono internally. |
| **Float32** | The numeric type we use for samples. Range: -1.0 to 1.0. |
| **Onset / transient** | A sharp moment in the audio (drum hit, consonant). |
| **BPM** | Beats per minute. |
| **Slice** | A short chunk of audio cut between two sample indices. |
| **Envelope** | A multiplier applied to a slice's start and end so it fades in and out. |
| **Time-stretch** | Change duration without changing pitch. We use rubberband. |
| **Pitch shift** | Change pitch without changing duration. Also rubberband. |
| **Resample** | Change duration *and* pitch by reading samples at a different rate. |
| **dBFS** | Decibels relative to full scale. -1 dBFS ≈ amplitude 0.891. |
| **Web Audio API** | Browser-native API for graph-based audio processing. |
| **AudioContext** | The Web Audio "engine" that runs the graph. |
| **MediaElementAudioSourceNode** | The Web Audio node that taps an `<audio>` element. |
| **AudioNode** | A Web Audio building block (gain, filter, oscillator, …). |
| **WaveShaper** | A node that applies a transfer function — used for distortion. |
| **Allpass filter** | A filter that changes phase but not amplitude — phaser building block. |
| **LFO** | Low-frequency oscillator, used to modulate other parameters. |
| **PyInstaller** | Tool that bundles a Python program + dependencies into a single distributable. |
| **`sys._MEIPASS`** | The directory PyInstaller's bootloader extracts the bundle into at runtime. |
| **Hardened runtime** | macOS sandboxing mode required for notarization. |
| **Notarization** | Apple's automated malware scan; output is a "ticket" we staple to the app. |
| **Gatekeeper** | macOS's launch-time signature/notarization check. |
| **`@loader_path`** | dyld variable — directory of the binary doing the loading. |
| **`install_name_tool`** | macOS tool to rewrite dylib reference paths in a binary. |

---

## 16. v0.1.x changes (Jan–May 2026)

This section consolidates what changed between v0.0.9 and v0.1.2 so
the section-by-section descriptions above don't have to be rewritten
inline. Each item links to either an ADR or the relevant section
above for deeper detail.

### Slicing

- **Nine slice resolutions instead of four.** `1/1` (whole-note,
  4 beats per slice), `1/2`, plus extreme micro-chops at `1/64` and
  `1/128`. The `res_map` in `detect_slice_points` now spans
  `0.25 → 32` subdivisions per beat. UI swapped from `gr.Dropdown`
  to `gr.Radio` rendered as a chip row (see §7).
- **MAX RANDOM mode.** New resolution that bypasses the BPM grid
  entirely. Each slice's duration is independently drawn from one
  of three categorical buckets (stutter 5-30 ms, chop 100-500 ms,
  held 1000-4000 ms), 1/3 probability each. Within each bucket,
  log-uniform sampling. The bucket gaps (no 30-100 ms or 500-1000 ms
  durations emitted) are intentional — see ADR-0012.
- **Auto-shuffle on MAX RANDOM.** Selecting MAX RANDOM in the radio
  triggers a `.change()` handler that auto-checks the existing
  `randomize slice order` checkbox. User can manually uncheck for
  "random durations, original order" mode. See ADR-0013.

### Upload & input

- **Universal file upload.** The single visible drop zone is now a
  `gr.File(file_types=None)` that accepts any audio or video file.
  A change handler routes audio files through directly to `audio_in`,
  and ffmpeg-extracts video files first. `audio_in` starts hidden
  (`visible=False`) and is revealed by the handler with the loaded
  path. See ADR-0009.
- **`gr.Audio` MIME validation cannot be bypassed** — see ADR-0009
  context for the false-start history.

### UI polish

- **Radios as chip rows.** `gr.Radio` styled as inline chips with
  the native dot hidden; selected state shown via cyan-bordered
  background. Applied globally across all skins.
- **Dark dropdowns.** `gr.Dropdown` had a stubborn white `.wrap-inner`
  background that the base `select` rule didn't reach. Fixed by
  adding `elem_classes=["slurm-dropdown"]` and using a universal-
  descendant selector (`.slurm-dropdown *`) to force theming. The
  popup options list is rendered into `document.body` so we also
  target `body > ul[role="listbox"]`. ADR-0014 §4.
- **In/out/seed textbox baseline pinning.** Gradio renders Textbox
  labels two ways depending on `info=` presence, causing visible
  inconsistency. Fixed by giving all three matching `info=` strings
  + flex-column layout with `justify-content: flex-end` to pin
  inputs to the same y-position regardless of label-area height.
  ADR-0014 §5.
- **`:focus-within` block highlight neutralized.** Gradio's default
  recolors block border + label to the accent color when any input
  is focused, making identical components look mismatched depending
  on which was clicked last. Overridden to keep block visually
  inert; the input itself shows focus via a subtle inner-border
  brighten. ADR-0014 §6.
- **Header click → subvoyant.com.** Both the Siena cat icon and the
  SIENA SLURMER title text are wrapped in `<a target="_blank">`
  with `.slurm-header-link` CSS that strips default anchor styling
  but adds `cursor: pointer` + brightness hover.
- **Hover gif easter eggs (×3):**
  - `.slurm-max-option` — Max gif on MAX RANDOM radio (right-slide).
    Tagged via INIT_JS by label text content.
  - `.slurm-max-popup` — Hoberman-Max gif on 🎲 randomize all button
    (bottom-up bouncy spring).
  - `.slurm-bob-option` — Bob gif on 📁 reveal temp files button
    (bottom-up bouncy spring).

  Each gif is base64-inlined as a Python constant alongside
  `_ICON_B64`. CSS uses `cubic-bezier(0.34, 1.56, 0.64, 1)` for
  the spring easing. Two were added because two testers each
  contributed feature suggestions.

### Utility & operational

- **🎲 Randomize all button** (`_randomize_all`) — scrambles 9 slurm
  parameters with musical-bias ranges. Output format, in/out trim,
  audio file, and seed are preserved.
- **📁 Reveal temp files button** (`_reveal_temp_dir`) — opens
  `SESSION_TMP_DIR` in Finder/Explorer/xdg-open. Useful for grabbing
  outputs before quit wipes the session dir.
- **Session-scoped temp file cleanup.** All temp files (audio
  outputs, video exports, intermediate WAVs, favicon PNG, extracted
  audio from video uploads) now live in a per-process subdir via
  `_new_temp_path()`. Cleaned by `atexit`; orphans from crashed
  prior sessions are swept on next launch. See ADR-0011.
- **Video render auto-burns FX.** If the user picks "FX-burned
  output" in the YouTube video panel without first clicking
  "burn FX to file", `render_video` now auto-burns from the current
  slider values. Was a silent dry-output bug before.
- **Browser tab favicon = Siena cat.** Set via JavaScript injection
  with setTimeout retries. `<link rel="icon">` and `favicon_path`
  both proven unreliable. See ADR-0010.
- **Header click → subvoyant.com.** Logo and title both link out.

### Build & distribution

- **`LICENSE` (GPL-3.0 + third-party notices) bundled into the DMG.**
  `build.sh` stages it alongside the `.app` and the beta-test notes.
- **`SLURMCORE_COMPARISON.md` bundled into the DMG.** Long-form
  guide explaining how Slurmify's method differs from general
  slurmcore practice, with sections aimed at both newcomers and
  engineers. Renamed in DMG to `Slurmify vs Slurmcore — Method Guide.md`.
- **DMG layout improvements:** `mktemp` staging dir + `Applications`
  symlink for canonical drag-to-install layout. `trap` ensures
  cleanup on early exit.

### Pipeline (`slurmify`)

- **`load_audio` extension support extended** to include video
  containers (`.mp4`, `.mov`, `.mkv`, `.webm`, `.wmv`, `.flv`, `.mpg`,
  `.mpeg`, `.3gp`, `.ts`, `.mts`, `.m2ts`, `.m4v`) plus more audio
  formats (`.opus`, `.wma`, `.ape`, `.alac`). librosa via audioread+
  ffmpeg handles them all transparently — but the actual upload
  path for non-audio goes through `_route_upload` → ffmpeg first
  (more efficient than letting librosa demux on every load).
- **Dancer-stuck-after-error bug** identified but not yet fixed.
  Cause: Gradio `.then()` chains break on `gr.Error`, so the
  hide-dancer step never fires when validation raises. The fix
  requires either pre-validating before the show step, or
  converting `process()` to a generator that yields hide-state in
  a finally clause. See ADR-0014 §7. Tracked for a future release.

### Gotchas catalog

ADR-0014 was added as a living catalog of Gradio behavior quirks
discovered during this work — MIME validation server-side, label-
rendering depending on `info=` presence, `:focus-within` block
highlight, `interactive=False` killing transport controls, etc.
First place to look when something Gradio-related does something
weird.

### Apple infrastructure note

`codesign --timestamp` calls `timestamp.apple.com` which goes down
occasionally (a few times a year). When build fails with
"The timestamp service is not available", it's not a code bug —
wait and rerun. Don't remove `--timestamp` (breaks notarization).

---

## 17. v0.1.3 changes (May 2026)

### Adaptive beat-grid slicing

`detect_slice_points()` in `slurmcore.py` was rewritten to follow the
actual beat positions detected by `librosa.beat.beat_track` rather than
a uniform grid extrapolated from a single global BPM estimate.

**Before (v0.1.2):** one BPM value estimated from the track; then a
perfectly regular grid was laid down for the entire file. On variable-tempo
material (live drums, any track with "feel") the grid drifted increasingly
out of sync with the audio as the file progressed.

**After (v0.1.3):** librosa returns a *list* of actual beat timestamps.
`detect_slice_points` subdivides or coarsens those beat *intervals* per-pair
rather than assuming uniform spacing. The grid now bends with the song —
on a click track you won't hear a difference; on live material, slice
boundaries land on real musical events.

### BPM override control

New text field in `slurm_ui.py` / `build_ui()`, below the slice resolution
picker. Accepts an optional integer or float. When filled in, the value is
passed to `librosa.beat.beat_track` as a `start_bpm` hint, anchoring it to
the right tempo octave. Useful when librosa halves or doubles the actual BPM
(e.g. detects 70 BPM on a 140 BPM track). Leave blank for auto-detect.

The value flows through:
`process()` → `slurmify()` → `detect_slice_points(bpm_override=...)`.

---

## 18. Modularisation — Phases 1–4 (v0.1.3, May 2026)

The original `app.py` grew to 3,569 lines by v0.1.2. Four successive
extraction phases split it into five focused modules without changing any
observable behaviour.

| Phase | ADR | What moved out | Result |
|---|---|---|---|
| 1 | ADR-0015 | `INIT_JS`, `CUSTOM_CSS`, base64 media → `ui_assets.py` | app.py ~2 100 lines |
| 2 | ADR-0016 | DSP (`slurmify`, `apply_fx`, `_fx_*`, `detect_slice_points`) → `slurmcore.py` | app.py ~1 320 lines |
| 3 | ADR-0017 | Filesystem IO (`load_audio`, `_write_audio`, `_asset`, session temp) → `slurmio.py` | app.py ~1 320 lines |
| 4 | ADR-0018 | Gradio UI (`build_ui`, `process`, `burn_fx`, `render_video`, `_quit_app`) → `slurm_ui.py` | app.py ~199 lines |

### Purity rules enforced across modules

| Module | Must never import |
|---|---|
| `slurmcore.py` | `os`, `sys`, `gradio`, `soundfile`, `shutil`, `subprocess` — pure DSP only |
| `slurmio.py` | `gradio` at the top level (one lazy import inside a try/except is permitted) |
| `slurm_ui.py` | `app` (circular); imports from `slurmio`, `slurmcore`, `ui_assets` only |

### For newcomers — why this matters

Before the split, editing a CSS rule meant opening a 3,500-line file,
scrolling past all the audio code, and hoping you didn't accidentally
break something on the other side of the file. After the split:

- Want to change the UI layout? Open `slurm_ui.py`.
- Want to add a new DSP effect? Open `slurmcore.py`.
- Want to add a new output format? Open `slurmio.py`.
- Want to change the look? Open `ui_assets.py`.
- Want to change how the app starts? Open `app.py`.

Each file has one job, and that job is clear from the filename.

### PyInstaller impact

Every local `.py` module must be in `hiddenimports` in `slurmify.spec`.
PyInstaller's static analysis auto-detects installed *packages* but not
local `.py` files. The current list is `ui_assets`, `slurmcore`, `slurmio`,
`slurm_ui`. Removing any entry causes the bundled `.app` to crash at startup
with `ModuleNotFoundError`.

---

*Last updated: 2026-05-07 · v0.1.6 · Stereo end-to-end through the slurmify pipeline (ADR-0021)*
