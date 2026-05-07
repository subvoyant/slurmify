# ADR-0019: Beat mask — per-beat dropout within each bar

- **Status:** Accepted
- **Date:** 2026-05

## Context

Users wanted a way to selectively remove specific beat positions from
the slurmify output — for example, "keep beats 1 and 3 of every bar,
drop 2 and 4" at 1/4 resolution, or "keep every other 16th-note" for
an Amen-break flavour.  This is fundamentally a repeating mask applied
to the slice list: keep slice i iff `mask[i % N]` is True, where N is
the number of note-subdivisions per bar at the chosen resolution.

## Decision

### DSP layer (`slurmcore.py`)

Added `bar_mask: list[bool] | None = None` to `slurmify()`.  After
step 3 (cutting into slices) and before step 4 (per-slice DSP), the
mask is applied with a single list comprehension:

```python
if bar_mask and not all(bar_mask):
    slices = [s for i, s in enumerate(slices) if bar_mask[i % len(bar_mask)]]
    if not slices:
        return np.zeros(1, dtype=np.float32), sr   # all masked → silence
```

`None` and all-True both skip the filter entirely (zero overhead on
the default path).  All-masked returns 1 sample of silence, keeping
the return contract `(ndarray, int)` valid and avoiding division-by-
zero in the downstream normalizer.

### UI layer (chip strip in `slurm_ui.py` + `ui_assets.py`)

A row of N toggle-chip buttons is rendered below the resolution Radio.
The container is a plain `gr.HTML('<div id="slurm-beat-mask"></div>')`
that INIT_JS writes into dynamically.  This keeps the Gradio layout
static while the chip content is dynamic and resolution-dependent.

**Chip count by resolution:**

| Resolution | Chips | Meaning |
|---|---|---|
| 1/1 | 1 | whole bar (rarely useful — included for completeness) |
| 1/2 | 2 | half notes |
| 1/4 | 4 | quarter notes = beats 1–4 |
| 1/8 | 8 | eighth notes |
| 1/16 | 16 | sixteenth notes |
| 1/32 | — | hidden (32 chips is too dense) |
| 1/64, 1/128 | — | hidden |
| MAX RANDOM | — | hidden (no fixed grid) |

Chips use circled Unicode digits (①–⑯) as labels.  Each chip carries
a `title=` tooltip showing beat number and resolution.

**JS → Python data flow:**

1. User clicks a chip → JS toggles `_beatMask[idx]` and immediately
   writes a snapshot to `window._slurmBeatMask = _beatMask.slice()`.
   No Python round-trip occurs.
2. When the Go button fires, the **first** step in the `.click()` chain
   is a `fn=None` JS-only step:
   ```python
   go_btn.click(
       fn=None,
       inputs=[],
       outputs=[bar_mask_val],
       js="() => { return [JSON.stringify(window._slurmBeatMask || [])]; }",
   ).then(fn=process, ...)
   ```
   Gradio calls the JS function, takes its return value, and routes it
   to `bar_mask_val` (the hidden `gr.Textbox`) through its own
   frontend→backend sync.
3. Python's `process()` receives `bar_mask_json`, `json.loads()` it,
   builds a `list[bool]`, and passes it to `slurmify()` as `bar_mask`.

**Why not write to the Textbox's `<textarea>` directly from JS?**

The obvious approach — use the React native-setter trick
(`Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set.call(el, v)`
then dispatch an `'input'` event) to push a value into the Textbox's
underlying `<textarea>` — does **not** work in Gradio 5.  Gradio 5
uses Svelte, not React.  Svelte's internal state is not updated by
DOM manipulation + event dispatch on the `<textarea>`; the component
continues to report its original `""` value to Python.  The
`fn=None + outputs=` route goes through Gradio's own state sync and
works reliably regardless of the frontend framework version.

**Why a hidden Textbox at all (not `gr.State`)?**

A `gr.State` update requires a Python round-trip.  Chip toggling must
be instantaneous with zero server latency.  The Textbox holds the
value passively; the Go-button's JS capture step is the only moment
Python ever needs to read it.

### Visibility + reset rules

`_slurmBuildBeatMask(resolution)` is called:
1. On page init (via a short `setInterval` poll until `#slurm-beat-mask`
   appears in the DOM) — builds the initial 16-chip strip for the
   default resolution 1/16.
2. On every `resolution.change()` via a **second, standalone** handler:
   ```python
   resolution.change(
       fn=None, inputs=[resolution], outputs=[bar_mask_val],
       js="(v) => { window.slurmBuildBeatMask(v); return ['']; }",
   )
   ```
   This is **not** a `.then()` step on the existing `_on_resolution_change`
   chain.  A chained `fn=None, outputs=[]` step stops firing after any
   preceding Python round-trip (e.g. a completed slurmify), so the chip
   strip would freeze at the last-built resolution until the page reloaded.
   A standalone `fn=None` with a real `outputs=` is the reliable pattern.
   The `return ['']` simultaneously resets `bar_mask_val` to all-on.

Every rebuild resets all chips to "on" (all-True) and resets
`window._slurmBeatMask` to a fresh all-true array, so switching
resolutions never carries a stale mask from a different note density.

### PATCH metadata

`bar_mask` is included in `render_video()`'s PATCH JSON blob under
`core.bar_mask` as the raw JSON string, preserving full round-trip
fidelity for any future "import patch" feature.

## Consequences

**Wins**
- Users can create off-beat patterns and rhythmic variations that are
  impossible with the existing controls.
- The feature is completely optional and zero-overhead when no chips
  are toggled off (bar_mask stays None).
- The chip strip hides itself for dense resolutions (1/32+) and MAX
  RANDOM, where it would be too cluttered or meaningless.
- The JS→Python bridge uses Gradio's own sync path, which is robust
  across Gradio version bumps.

**Costs**
- One new DOM element (`#slurm-beat-mask`) and one hidden textbox
  (`#slurm-beat-mask-val`) in the layout.
- The `go_btn.click()` chain now has four steps instead of three; the
  first (JS capture) is invisible to the user but adds one client-side
  round-trip before the dancer GIF appears.

## Risks

- If `window._slurmBeatMask` is undefined when Go fires (e.g. the
  INIT_JS chip-builder hasn't run yet), the JS capture step returns
  `"[]"`, which process() treats as all-on — graceful degradation.
- Very short audio that yields fewer slices than `len(bar_mask)` still
  works correctly — the modulo wraps around as expected.

## See also

- ADR-0012 — MAX RANDOM trimodal distribution (beat mask hides for MAX
  RANDOM for the same reason: no fixed beat grid to mask)
- ADR-0013 — auto-shuffle for MAX RANDOM (same resolution.change chain
  that now also rebuilds the chip strip)
- ADR-0014 § 13 — Gradio 5 accordion DOM: closed accordions have no
  DOM children (same pattern we worked around for `#slurm-fx-audio`)
