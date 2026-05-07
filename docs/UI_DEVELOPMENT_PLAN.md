# UI Development Plan — Subvoyant SIENA Slurmer

**Status:** Living document · v0.1.4 baseline · May 2026  
**Audience:** developers and decision-makers  
**Scope:** everything from near-term Gradio improvements through long-term
architecture decisions about replacing Gradio entirely

---

## 1. Current state assessment

### What Gradio gives us

Gradio was the right choice to reach the first usable version quickly. It
provides:

- A fully functional browser UI from pure Python declarations in `build_ui()`.
- Audio waveform playback via the WaveSurfer 7 integration in `gr.Audio`.
- File upload with drag-and-drop, including the custom `gr.File` universal
  drop zone (ADR-0009).
- A WebSocket-backed event system for Python ↔ browser communication that
  handles concurrent requests, file serving, and progress bars.
- A runnable server — no separate frontend build step, no npm, no Node.

In early development this let us focus entirely on audio DSP without
learning a full frontend stack. That tradeoff has now largely paid off —
the DSP engine (`slurmcore.py`) is solid and the modularisation is complete.
The UI layer is now the limiting factor.

### Where Gradio creates friction

The following friction points are documented from real development experience.
Each is currently worked around with CSS hacks or JS injection; all of them
would either go away or become trivially solvable with a purpose-built
frontend.

#### A — Structural constraints

| Problem | Impact | Current workaround |
|---|---|---|
| `build_ui()` is 635+ lines of nested `with` blocks | Hard to navigate, no component isolation | Phase 4 split; at least now contained in `slurm_ui.py` |
| Gradio 6 CSS selectors are fragile across minor releases | UI breaks silently after `pip install --upgrade gradio` | Pinned version + `!important` everywhere |
| No component-level encapsulation | Sliders for different concerns are in the same flat namespace | Accordion groups + `elem_id` discipline |
| WaveSurfer's `<audio>` lives in a shadow DOM | `querySelectorAll('audio')` misses it; custom `_fxWalk` required | ADR-0003 + `_fxWalk` in INIT_JS |
| `gr.Audio` rejects non-audio MIME types server-side | Cannot upload video files via the audio input widget | ADR-0009: `gr.File(file_types=None)` + `_route_upload` |
| `gr.Blocks(js=...)` and `gr.HTML` injection are unreliable | INIT_JS (500 lines of JS) cannot be delivered normally | ADR-0004: `head=` injection |

#### B — UX friction points

| Problem | User impact | Severity |
|---|---|---|
| **Dancer stuck on error** | If slurmify raises `gr.Error`, the loading animation never disappears | High |
| No waveform for the slurm output while it loads | User has no indication of progress after the progress bar completes | Medium |
| FX panel requires a manual "open accordion" click every session | Persists closed; preference not saved | Medium |
| No visual feedback while burn FX is running | The burn button goes dead for several seconds with no spinner | Medium |
| No A/B comparison between input and output audio | User must switch between two players manually | Medium |
| `gr.Audio` play controls are WaveSurfer-styled (not native) | Pause/play/scrub inconsistency across browser | Low |
| Slider labels are fixed-size Gradio components | Cannot resize labels to match the dark/compact aesthetic without `!important` overrides | Low |
| The "skin picker" `<select>` is inside a `gr.HTML` block | Can't be a proper Gradio component; doesn't participate in state | Low |

#### C — Developer experience

| Problem | Dev impact |
|---|---|
| No automated tests | Every change requires a full manual run |
| CSS changes require a full restart (no hot-reload for CUSTOM_CSS) | Slow CSS iteration |
| JS changes in INIT_JS cannot be inspected via browser source maps | Debugging requires `console.log` tracing only |
| 1,800-line `ui_assets.py` has no sub-structure | JS and CSS are both monolithic strings |

---

## 2. Near-term improvements — within Gradio

These are improvements achievable without replacing Gradio. Each is
self-contained and can be shipped independently.

### 2.1 Fix the dancer-stuck-on-error bug (HIGH — ADR-0014 §7)

**Problem:** `process()` raises `gr.Error` on validation failure. Gradio's
`.then()` chain stops executing on error, so the "hide dancer" step never
runs. The Siena animation loops forever.

**Fix options (pick one):**

Option A — Pre-validate before showing the dancer:
```python
go_btn.click(
    fn=validate_inputs,          # new: fast validation, raises gr.Error early
    inputs=[audio_in, speed, ...],
    outputs=[],                  # no output on failure
).success(                       # .success() only runs if fn didn't raise
    fn=lambda: gr.Image(visible=True),
    outputs=dancer,
).then(
    fn=process, ...
).then(
    fn=lambda: gr.Image(visible=False), outputs=dancer,
)
```

Option B — Convert `process()` to a generator with a `finally` block:
```python
def process(...):
    try:
        # ... validation ...
        yield result_path
    finally:
        pass  # can't yield from finally; dancer hide must be a separate .then()
```
Note: generators with `finally` work in Gradio 5.31+; the `.then()` chain
after a generator step fires after the last yield, whether or not the
generator raised. Needs testing on Gradio 6.

**Recommended:** Option A. It's simpler, doesn't require Gradio version
testing, and has the bonus of not animating the dancer on trivially-invalid
input (e.g. nothing uploaded yet).

**Effort:** ~30 min. **ADR needed:** no (already documented in ADR-0014 §7).

### 2.2 Burn FX progress indicator (MEDIUM)

**Problem:** burn FX for a long stereo file (especially with the delay loop)
can take 5–15 seconds. The button goes dead with no feedback.

**Fix:** convert `burn_fx()` into a `gr.Progress`-yielding generator similar
to `process()`. Report progress after each FX stage (distortion → ring →
delay → phaser → write).

```python
def burn_fx(..., _progress=gr.Progress()):
    _progress(0.0, desc="Loading…")
    y, sr = librosa.load(...)
    _progress(0.15, desc="Applying distortion…")
    # ...
    _progress(1.0, desc="Done")
    return path
```

**Effort:** ~1 hour. **ADR needed:** no.

### 2.3 Persist FX panel open state (LOW–MEDIUM)

**Problem:** the FX accordion and video accordion close on page reload.
Power users who always use FX have to re-open it every session.

**Fix:** use localStorage to persist open/closed state. INIT_JS can toggle
the panel open via the `.open` property of the `<details>` element that
Gradio 6 uses for accordions. On page load, check localStorage and
re-open if set.

```javascript
// In INIT_JS — after DOM ready
var fxPanel = document.getElementById('slurm-fx-panel');
if (fxPanel && localStorage.getItem('slurmFxOpen') === '1') {
    fxPanel.open = true;
}
fxPanel && fxPanel.addEventListener('toggle', function () {
    localStorage.setItem('slurmFxOpen', fxPanel.open ? '1' : '0');
});
```

**Effort:** ~1 hour. **ADR needed:** no (INIT_JS is already injected via `head=`).

### 2.4 FX parameter presets (MEDIUM)

**Problem:** there's no way to save a good FX patch. Every session starts
at zero. Heavy users iterate the same settings repeatedly.

**Fix:** add 4–6 preset buttons above the FX sliders. Each button fires a
JS callback that sets all `window.slurmFx.*` values at once. Store
user-defined presets in localStorage.

Preset design: one button = "clear" (all zeros), plus 3–4 named presets
(e.g. "tape hiss", "lo-fi crunch", "dark hall", "glitch storm"). Colours
match the active skin.

This is pure JS — no Python round-trip. The slider Gradio components would
need to be updated too (their Python-side values drift out of sync if JS sets
them directly); easiest fix is to expose a `gr.Button` per preset that fires
`fn=None, js=...` and returns the new slider values to the `outputs` list.

**Effort:** ~3 hours. **ADR needed:** yes (living JS-only state management pattern).

### 2.5 A/B player — quick toggle between input and slurm output (MEDIUM)

**Problem:** the only way to compare input vs. output is to physically
scrub between two separate players. Disorienting when testing subtle settings.

**Fix:** add a single toggle button in the output row labelled "A/B". When
active, it mirrors the slurm output's current playhead position and
simultaneously plays the original upload through a third hidden `<audio>`
element (similar to the FX preview element). Clicking A/B switches which
audio is audible without stopping playback.

This is achievable in pure JS with a third hidden `<audio>` element declared
in a `gr.HTML` block, wired to the upload path via the same src-mirroring
mechanism already used for the FX preview.

**Effort:** ~4 hours. **ADR needed:** yes (extends the src-mirroring pattern from ADR-0003).

### 2.6 Output format persistence (LOW)

**Problem:** output format defaults to "wav" every session. Users who always
export mp3 reset it every time.

**Fix:** mirror the `output_format` dropdown's value to localStorage in a
`dropdown.change(fn=None, js=...)` handler. On page load, restore from
localStorage. Identical pattern to the skin picker.

**Effort:** ~30 min. **ADR needed:** no.

### 2.7 Waveform zoom on the output player (LOW)

**Problem:** WaveSurfer 7 defaults to showing the entire waveform at once.
For a 3-minute slurmified output, individual slice textures are invisible
at full zoom.

**Fix:** set `min_length=0` (already handled) and expose WaveSurfer's zoom
controls via a JS-injected range input overlaid on the player. WaveSurfer
exposes `wavesurfer.zoom(pxPerSec)` — we call it from our injected script.

**Effort:** ~2 hours. **ADR needed:** no.

---

## 3. Medium-term improvements — custom components within Gradio

These require either a custom Gradio component (using the Svelte component
SDK) or a significant JS injection.

### 3.1 Custom XY pad for ring-mod / phaser (MEDIUM complexity)

Two of the four FX have natural 2D relationships: ring-mod (freq × depth)
and phaser (rate × depth). Replace two pairs of sliders with a single XY
pad per effect — a draggable point on a 2D canvas.

Implementation: `gr.HTML` with an SVG canvas that fires `window.slurmFx.*`
calls on `pointermove`. No Gradio component needed — pure HTML + JS. The burn
FX path receives the values via hidden `gr.Number` inputs that the JS updates.

**Effort:** ~5 hours. **ADR needed:** yes.

### 3.2 Spectrogram display for the output (HIGH complexity)

Replace or augment the waveform view with a live spectrogram rendered in
a `<canvas>` using the `AnalyserNode` from the FX Web Audio graph. Since the
analyser is already in the graph (it powers the hardware-skin VU meter), this
requires only a second `canvas` and an additional draw call in the rAF loop.

The spectrogram would be overlaid on the existing player area, toggled by a
button. For the acid skin, this would look especially good.

**Effort:** ~6 hours. **ADR needed:** no (extends existing analyser use).

### 3.3 Slice grid visualizer (HIGH complexity)

Show the detected slice boundaries overlaid on the input waveform before
slurmifying. Let the user see where MAX RANDOM landed, or how sensitive the
transient detection is, before committing to the full run.

This requires exposing `detect_slice_points()` as a fast preview endpoint
(a new Gradio button that runs only the slice-detection step and returns
slice positions as JSON), then drawing them on a `<canvas>` in INIT_JS.

The result is a "preview slices" button that shows a waveform + marker
visualization in under 1 second.

**Effort:** ~8 hours (DSP endpoint + canvas drawing). **ADR needed:** yes.

### 3.4 Drag-to-reorder slices (VERY HIGH complexity, Gradio-hostile)

Allow the user to manually drag slice blocks into a custom order after
slurmify runs. This requires:

1. A new data structure in `process()` that exposes the individual slice
   files instead of concatenating them.
2. A draggable block UI (pure JS).
3. A "render from order" endpoint that concatenates slices in the user's
   chosen sequence.

This is at the edge of what Gradio can host comfortably and is a strong
signal that a purpose-built frontend would serve better.

**Effort:** ~20 hours minimum. **ADR needed:** yes.

---

## 4. Long-term — beyond Gradio

### The core tension

Gradio was designed for ML demos, not creative tools. Its strengths are:

- Rapid prototyping
- Automatic type coercion between Python and browser
- No frontend build pipeline required

Its weaknesses as a creative-tool host are:

- No composable component model (no React-style isolation)
- UI state lives in Python (slow round-trips for real-time parameter feedback)
- CSS theming requires `!important` fights against Gradio's own styles
- The WaveSurfer integration is opaque and version-locked
- Layout is form-like, not spatial
- No drag-and-drop UI primitives for creative tools (patch bays, XY pads,
  step sequencers)

The Web Audio FX chain already bypasses Gradio entirely — it runs fully in
the browser. The slider `change` events do fire Python-side, but only to
mirror values back to JS. A purpose-built frontend would eliminate all that
indirection.

### Option A — Tauri + React (RECOMMENDED long-term path)

**What it is:** Tauri wraps a web frontend (HTML/CSS/JS or any framework)
in a native macOS `.app`. The Python backend (currently the uvicorn process
Gradio launches) would become a sidecar process. The frontend communicates
with the backend via Tauri's IPC or via a local HTTP/WebSocket channel.

**Why this fits Slurmify:**
- `slurmcore.py` is already completely UI-agnostic — it takes NumPy arrays
  and returns NumPy arrays. Wrapping it behind a JSON API endpoint is trivial.
- `slurmio.py` handles all file I/O — the backend API surface maps cleanly
  onto REST-style calls: `POST /slurmify`, `POST /burn-fx`, `GET /files/{id}`.
- The FX preview chain (Web Audio) already lives in the browser. A React
  frontend can host it without any Gradio glue.
- Tauri produces a macOS `.app` with code signing — same distribution
  model as today, smaller bundle (no bundled Python chromium).

**What changes:**
- `app.py` and `slurm_ui.py` become a lightweight FastAPI server
  (Gradio is already FastAPI under the hood — we'd just remove Gradio).
- The React frontend replaces `build_ui()`, `INIT_JS`, and `CUSTOM_CSS`.
- `slurmcore.py`, `slurmio.py`, and `ui_assets.py` (minus the Gradio-
  specific parts) stay as-is.
- PyInstaller would be replaced by Tauri's bundler.

**Risks:**
- Frontend build pipeline (Vite, TypeScript, React) adds onboarding cost.
- Audio file serving (currently handled by Gradio's file-serving middleware)
  must be implemented in the FastAPI layer.
- No Gradio progress bar — must implement SSE or WebSocket progress events.

**Effort estimate:** 3–4 weeks for a functional replacement of all current
Gradio features; an additional 2 weeks for the creative-tool UI features
that Gradio can't host (slice visualizer, XY pads, slice grid editor).

### Option B — Electron + React

Same frontend approach as Tauri, but Electron bundles a full Chromium
instance rather than using the system WebView. Produces a ~150 MB heavier
bundle but has better cross-platform browser compatibility and a larger
ecosystem of tooling.

For Slurmify (macOS-only, small user base, Apple Silicon targets), Tauri is
the better choice — smaller bundle, faster startup, better macOS integration.

### Option C — Svelte/SvelteKit custom Gradio components

Stay within Gradio but build proper Svelte components for the custom
interactive elements (XY pad, slice visualizer, waveform editor). Gradio's
component SDK supports this.

**Pros:** incremental adoption, keeps the Python integration, no new runtime.

**Cons:** the Gradio component SDK is not well-documented for complex
interactive elements; the component lifecycle fights Gradio's Svelte runtime;
every upgrade of Gradio risks breaking custom components.

**Verdict:** Use for isolated widgets (XY pad, spectrogram toggle). Don't
use as the primary UI architecture.

### Option D — Pure web app (no desktop wrapper)

Eliminate the macOS `.app` entirely. Run `app.py` as a local server and
have users open `http://127.0.0.1:7860` themselves.

**Pros:** eliminates all PyInstaller and Tauri complexity. The user-facing
UI becomes a standard SPA.

**Cons:** onboarding requires Python and pip (harder than DMG drag-install).
No Dock icon, no `⌘Q`, no file-association, no macOS-native file picker.

**Verdict:** too much regression in user experience for the target audience
(music producers who may not be developers). Keep the native app wrapper.

---

## 5. Recommended development sequence

### Phase 5 (next sprint, ~1 week) — Gradio polish

1. Fix dancer-stuck-on-error bug (§2.1) — highest user-visible impact
2. Burn FX progress indicator (§2.2)
3. Output format persistence (§2.6)
4. FX panel open state persistence (§2.3)

These four together remove the most glaring UX roughness and are all
achievable within the current Gradio + INIT_JS architecture.

### Phase 6 (~2 weeks) — Gradio creative features

5. FX parameter presets (§2.4)
6. A/B player (§2.5)
7. Waveform zoom (§2.7)
8. XY pad for ring-mod / phaser (§3.1)
9. Spectrogram overlay via existing analyser (§3.2)

After Phase 6, the Gradio version of Slurmify would be a polished, feature-
complete creative tool. If it's still the right host at that point, continue
with §3.3 (slice visualizer). If the Gradio friction is still significant,
Phase 7 should be the Tauri migration.

### Phase 7 (~5–6 weeks) — Tauri + React migration

10. FastAPI backend: migrate Gradio event handlers to REST + WebSocket
    endpoints. `slurmcore.py` and `slurmio.py` are untouched.
11. React frontend: reimplement `build_ui()` layout as React components.
    The FX Web Audio chain moves from INIT_JS strings to real TypeScript.
12. Tauri wrapper: replace PyInstaller with Tauri bundler. Re-establish
    macOS code signing and notarization.
13. Feature parity testing: verify all current Gradio features work.
14. New features enabled by the migration: slice grid editor (§3.4),
    drag-to-reorder, native file picker, undo/redo, patch save/load.

---

## 6. ADRs to write for Phase 5

| Decision | ADR number |
|---|---|
| Dancer-stuck fix (Option A vs B) | 0019 |
| FX parameter presets pattern (JS-only state + localStorage) | 0020 |
| A/B player architecture | 0021 |

---

## 7. Known CSS technical debt

The following CSS hacks in `ui_assets.py` would either be eliminated by the
Tauri migration or should be cleaned up during Phase 6:

| Hack | Why it exists | Risk |
|---|---|---|
| `!important` on nearly every color rule | Override Gradio's own theme variables | Breaks if Gradio changes variable names |
| `.slurm-dropdown *` universal selector | `gr.Dropdown` popup renders outside its parent | Affects unrelated `ul[role="listbox"]` elements if any other popup appears |
| `info=` on every textbox to force label alignment | Gradio renders labels differently with/without `info=` | Must add matching empty `info=` strings to any new textboxes |
| `#slurm-skin-picker` inside `gr.HTML` | Skin picker can't be a Gradio component | Not participates in Gradio state serialization |
| `var(--slurmBg)` custom property not a Gradio standard | Workaround for skin-switching | Must be set in `:root` before any skin CSS |
| 4× `setTimeout` favicon retries | `<link rel="icon">` gets overwritten by Gradio | Will be unnecessary with a purpose-built frontend |

---

*Last updated: 2026-05-07 · v0.1.4*
