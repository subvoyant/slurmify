# ADR-0020: Note-mode time parameters — per-slider ms ⇄ ♪ toggle

- **Status:** Accepted
- **Date:** 2026-05
- **Version:** 0.1.5

## Context

Slurmify's musical time parameters — stutter skip length, beat trim
start/end, and beat gap — were previously expressed only in
milliseconds.  Musicians naturally think in note values: "make the gap
between beats a 1/16th" is more intuitive than "make the gap 125 ms",
and the latter only happens to be right at 120 BPM.

We wanted a way to express these four parameters in note fractions
(1/64 → 2 whole notes, with dotted/triplet variants) while preserving
the existing ms knobs for users who want exact millisecond control or
who are working below note-grid resolution.

The user's request was for *both* — let each slider be either ms or
notes, decided per-slider.  Three UI patterns were considered:

1. **Per-slider toggle** (chosen) — small radio chip "ms ⇄ ♪" beside
   each slider.  Mutually exclusive: only one input is visible at a time.
2. **Both visible, "note overrides if set"** — slider AND dropdown
   visible side-by-side; non-empty dropdown wins.  Doubles the vertical
   density of the bottom of the panel.
3. **Both visible, live-linked** — both controls rendered, edits in
   either auto-update the other.  Cleanest UX but requires live BPM
   in the browser, which we don't have until librosa runs server-side.

Pattern 1 won because:

- It keeps layout calm — four musical sliders × two visible inputs each
  would crowd the panel.
- The conversion ambiguity disappears: only one value is "live".
- The asymmetry of pattern 3 (BPM not known until processing) becomes
  a non-issue.

## Decision

### DSP layer (`slurmcore.py`)

**`_note_to_ms(note: str | None, bpm: float) -> float`** — new helper
parsing the note grammar:

```
"1/N"      whole-note fraction (1/4 = quarter note = 1 beat at 4/4)
"1/N."     dotted (× 1.5)
"1/NT"     triplet (× 2/3)
"1" / "2"  whole-note multiples
```

Returns 0.0 for None / empty / unparseable input or non-positive BPM,
so the caller can use the result directly as a "no override" signal.

**`detect_slice_points` now returns `(positions, effective_bpm)`** —
the BPM the slicer landed on (detected, overridden, or default for
MAX RANDOM).  This is the single source of truth for note-mode
conversion: a "1/16 gap" lines up rhythmically with a 1/16-note slice
resolution because both use the same BPM.  See §single-bpm below.

**`slurmify` accepts four new optional `*_note` parameters**, one per
musical slider.  After `detect_slice_points` returns, slurmify
converts non-empty notes to ms and overrides the matching `_ms` value:

```python
if stutter_skip_note:
    ms_from_note = _note_to_ms(stutter_skip_note, effective_bpm)
    if ms_from_note > 0:
        stutter_skip_ms = ms_from_note
```

The override only fires when the conversion produces a positive value,
keeping silent failure modes (bad note string) graceful.

### UI layer (`slurm_ui.py` + `ui_assets.py`)

Each musical slider now ships as a four-component group:

| Component                | Type            | Visibility        |
|--------------------------|-----------------|-------------------|
| `*_ms` slider            | `gr.Slider`     | when mode == "ms" |
| `*_note` dropdown        | `gr.Dropdown`   | when mode == "♪"  |
| `*_mode` radio chip      | `gr.Radio`      | always            |
| `slurm-unit-hint-*` div  | `gr.HTML`       | always            |

`_swap_unit_mode(mode) -> (gr.update, gr.update)` toggles slider /
dropdown visibility.  Wired to each mode radio's `.change` event;
visibility updates apply instantly.

The hint span is filled by JS in INIT_JS — never a Python round-trip.
JS reads:
- The active mode from the radio.
- The active value from whichever input is visible.
- The active BPM from the `#slurm-bpm-override` textbox (defaulting
  to 120 if blank).

…and writes "≈ NN ms @ BPM" or "≈ 1/N @ BPM" to the hint, refreshed
every 250 ms.  See §bpm-source-asymmetry for the BPM caveat.

### localStorage persistence

Each toggle's mode is persisted under the key `slurm_unit_<tag>` —
parallel to the existing skin-switcher pattern (ADR-0007).  Restore
runs on page load via a poll-and-click loop until the radio elements
exist, then stops.

### MP4 metadata (ADR-0008 extension)

`render_video()` now stores eight extra keys in the PATCH JSON `core`
dict — `(*_mode, *_note)` pairs, one per slider.  Older PATCH blobs
from v0.1.4 and earlier won't have these keys; the importer should
treat missing keys as `("ms", "")` (full backward compatibility).

## Single-BPM rule

> The BPM used by `_note_to_ms` MUST be the same BPM used by
> `detect_slice_points` to build the slice grid.

This is the load-bearing invariant.  Without it, a user who selects
"1/16 gap" at the same time as "1/16 slice resolution" would get a
gap that drifted out of phase with the slice grid — defeating the
musicality the feature is supposed to provide.

`detect_slice_points` now returns its effective BPM precisely so
`slurmify` can forward that exact value into the conversions.  No
recomputation, no second `librosa.beat.beat_track` call.

## BPM source asymmetry (Python vs. JS)

The Python pipeline has access to librosa-detected BPM.  The browser
does not — detection runs server-side at slurmify time.  The live
hint in INIT_JS therefore uses:

1. The BPM override textbox if filled.
2. 120 (matching `DEFAULT_BPM` in slurmcore) as fallback.

This is a known approximation, surfaced to the user via the hint's
"@ NNN BPM" suffix and the bpm_override textbox `info=` line.  Users
who care about exactness can type their track's BPM into the override
to get a precise hint AND lock the slice grid in place.

## Why ms is still useful

The `envelope_ms` slider is intentionally NOT included in the
note-mode toggle.  Anti-click envelopes operate at sub-musical scale
(0–20 ms; far below 1/128 even at 200 BPM) — note units would be a
footgun there.  This is documented in CLAUDE.md alongside the four
musical-time parameters.

## Consequences

**Pros**

- Musicians can think in their native unit per slider.
- The slicer's BPM and the time-parameter BPM are guaranteed to match
  by construction.
- Backward compatible: every legacy caller (PATCH metadata reload,
  scripted tests, prior render_video API) keeps working — note args
  default to None / "" and the existing ms args win.

**Cons / future work**

- The browser-side hint is approximate when no BPM override is set.
  A future enhancement could surface the librosa-detected BPM after
  one slurmify run completes, then drive the hint from that.
- _randomize_all only randomises the stutter-skip note dropdown,
  matching the original behaviour where only stutter_skip_ms (not
  trim/gap) was randomised.  Adding trim/gap to randomise would be
  a separate UX decision.
- The MAX RANDOM resolution skips beat detection, so its effective
  BPM falls back to override-or-120.  This is correct (note-mode
  parameters in MAX RANDOM are an unusual combination anyway), but
  worth noting to anyone debugging unexpected timing there.

## References

- [ADR-0007](0007-skin-system-data-skin.md) — established the
  localStorage persistence pattern.
- [ADR-0008](0008-self-describing-mp4.md) — PATCH JSON schema that
  this ADR extends.
- [ADR-0012](0012-max-random-trimodal.md) — MAX RANDOM bypasses the
  beat grid; documented above as the BPM-fallback edge case.
- [ADR-0014](0014-gradio-quirks-collected.md) — first place to look
  for any `gr.Radio` / `gr.Dropdown` rendering oddities encountered
  while iterating on the chip toggle styling.
- [ADR-0019](0019-bar-mask-beat-dropout.md) — adjacent musical-UX
  feature using a similar chip-style control aesthetic.
