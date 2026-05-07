# ADR-0016: Extract pure DSP into `slurmcore.py` (Phase 2)

- **Status:** Accepted
- **Date:** 2026-05-06

## Context

After Phase 1 (ADR-0015) extracted `INIT_JS`, `CUSTOM_CSS`, and the base64
assets into `ui_assets.py`, `app.py` stood at ~1,840 lines.  Roughly half
of those remaining lines were pure audio DSP — `detect_slice_points`,
`apply_envelope`, `slurmify`, and the four `_fx_*` helpers — interleaved with
Gradio UI wiring, file I/O, and process management.

Mixing DSP and I/O in the same function makes both harder to reason about:

- `slurmify()` called `load_audio()` (I/O) and `_write_audio()` (I/O),
  preventing any test of the DSP logic without an actual file on disk.
- `burn_fx()` called `librosa.load()`, raised `gr.Error`, and called
  `_write_audio()` — it could not be called from a context without Gradio.
- The four `_fx_*` helpers were pure numpy but were defined in the same file
  as `gr.Blocks()`, making it hard to spot that they had no Gradio dependency.

## Decision

**Extract all pure DSP into `slurmcore.py`.**

`slurmcore.py` contains exactly:

| Name | What it is |
|---|---|
| `detect_slice_points` | Beat-grid + transient-snap slice-point engine (unchanged interface) |
| `apply_envelope` | Per-slice fade-in/out (unchanged interface) |
| `slurmify` | Main slurm pipeline — **refactored** (see IO Boundary section) |
| `_fx_distortion` | Tanh waveshaper — pure numpy (unchanged) |
| `_fx_ring_mod` | Amplitude modulation — pure numpy (unchanged) |
| `_fx_delay` | Tape delay with feedback — pure numpy (unchanged) |
| `_fx_phaser` | 4-stage allpass phaser — pure numpy + scipy.signal (unchanged) |
| `apply_fx` | **New function** — pure DSP core factored out of `burn_fx` |

`app.py` imports all eight names:

```python
from slurmcore import (
    detect_slice_points,
    apply_envelope,
    slurmify,
    _fx_distortion,
    _fx_ring_mod,
    _fx_delay,
    _fx_phaser,
    apply_fx,
)
```

`slurmify.spec` gains `"slurmcore"` in `hiddenimports`.

## IO Boundary Refactor

The key architectural decision of Phase 2 is **where the IO boundary sits**:
all file operations are the caller's responsibility; `slurmcore.py` never
reads or writes files.

### `slurmify` — new signature

**Before (monolithic):**
```python
def slurmify(input_path: str, ..., output_format: str = "wav") -> str:
    y, sr = load_audio(input_path)
    ...
    return _write_audio(out, sr, output_format)
```

**After (pure DSP):**
```python
def slurmify(y: np.ndarray, sr: int, ...) -> tuple[np.ndarray, int]:
    ...
    return out, sr
```

`process()` in `app.py` now does the load/write wrapping:

```python
y, sr     = load_audio(audio_file)
y_out, sr = slurmify(y, sr, ...)
return _write_audio(y_out, sr, output_format)
```

### `apply_fx` — new name, new boundary

**Before:** `burn_fx()` in `app.py` was monolithic — it loaded the file,
ran the FX chain, and wrote the output.

**After:** the pure DSP portion is now `apply_fx(y, sr, ...) → (ndarray, int)`
in `slurmcore.py`.  `burn_fx()` remains in `app.py` as a thin Gradio wrapper:

```python
def burn_fx(audio_path, dist_drive, ...):
    if not audio_path or not os.path.exists(str(audio_path)):
        raise gr.Error("Run slurmify first — no output to apply FX to.")
    y, sr = librosa.load(audio_path, sr=None, mono=False)
    was_mono = y.ndim == 1
    if was_mono:
        y = y[np.newaxis, :]
    y, sr = apply_fx(y, sr, ...)          # ← slurmcore
    export = y[0] if was_mono or y.shape[0] == 1 else y
    return _write_audio(export, sr, out_fmt)
```

`render_video()` calls `burn_fx()` (unchanged — it already hands off a file
path).  No change required to the video export path.

## Purity rule for `slurmcore.py`

`slurmcore.py` must never import any of:

```
os  sys  soundfile  gradio  shutil  subprocess  tempfile  pathlib
```

Allowed imports:

```
random  numpy  librosa  pyrubberband  scipy.signal (local inside _fx_phaser)
```

This rule is enforced by the static AST check in Task 22's verification step
and is documented at the top of `slurmcore.py`.

## Dual FX Channel Constraint

Every `_fx_*` function has a matching Web Audio API node in `INIT_JS`
(`ui_assets.py`).  The Python path runs at export time; the JS path runs in
real time for zero-latency preview.  They share only numeric slider values.

Adding, removing, or changing any FX parameter requires edits in **both**:
1. `slurmcore.py` — the `_fx_*` function and `apply_fx()` signature
2. `ui_assets.py` — the matching Web Audio node in `INIT_JS`

Failing to update both means "burn FX" sounds different from the preview.
See ADR-0015 §dual-fx for the original statement of this invariant.

## Target Four-Module Architecture (updated progress)

```
app.py        — bootstrap + Gradio launch  (~20 lines)        FUTURE
ui_assets.py  — static browser content (DONE — ADR-0015)
slurmcore.py  — pure audio DSP            (DONE — this ADR)
slurmio.py    — filesystem IO             (Phase 3: load_audio, _write_audio,
                                            temp-file management)
slurm_ui.py   — Gradio orchestration     (Phase 4: build_ui, process,
                                            render_video, _quit_app)
```

After Phase 2, `app.py` is ~1,466 lines (down from 3,569 before Phase 1).
Phase 3 (`slurmio.py`) will extract `load_audio`, `_write_audio`,
`_new_temp_path`, `_cleanup_session_tmp`, and the session-temp machinery.

## Consequences

**Wins**

- `slurmcore.py` is independently importable and testable without Gradio,
  soundfile, or a real audio file on disk.
- `slurmify()` and `apply_fx()` are now pure functions: same input → same
  output, no filesystem side effects.
- `burn_fx()` in `app.py` is now a thin, readable wrapper rather than a
  mixed-concerns monolith.
- `app.py` drops from ~1,841 lines to ~1,466 lines.

**Costs / risks**

- **Interface change to `slurmify()`.** Any call site that passes
  `input_path=` or expects a `str` return value will break.  There is
  exactly one call site (`process()` in `app.py`) and it has been updated.
  No external callers exist.

- **One new `hiddenimports` entry** (`"slurmcore"`) in `slurmify.spec`.
  If removed, the bundled `.app` will crash with
  `ModuleNotFoundError: slurmcore`.  The entry is now present and must
  not be removed.

- **`burn_fx()` shape contract.** The new `burn_fx()` promotes mono input to
  2-D before calling `apply_fx()`, then squeezes back.  The squeeze logic
  must match what `_write_audio` / soundfile expects: `(n,)` for mono,
  `(n, channels)` for stereo (note: soundfile's convention is transposed
  relative to the `_fx_*` convention of `(channels, n)`).  The existing
  `export = y[0] if was_mono or y.shape[0] == 1 else y` handles this.

## See also

- ADR-0015 — Phase 1 (ui_assets.py extraction), dual FX channel invariant
- ADR-0001 — original "single file by design" rationale
- ADR-0011 — session-scoped temp directory (affects Phase 3 target)
- `slurmcore.py` — the file created by this decision
- `app.py`'s `burn_fx()` — the thin Gradio wrapper that replaced the monolith
