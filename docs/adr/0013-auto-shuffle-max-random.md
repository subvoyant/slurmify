# ADR-0013: Selecting MAX RANDOM auto-checks the shuffle box

- **Status:** Accepted
- **Date:** 2026-05 (v0.1.0)

## Context

When MAX RANDOM was first shipped (with log-uniform durations and then
trimodal — see ADR-0012), users reported it didn't sound random.
Investigation showed the slice DURATIONS were genuinely varied (the
debug print confirmed it), but the PERCEPTION was of "the original
song with random fades."

The cause: `randomize slice order` (the existing checkbox) defaults
to off. With MAX RANDOM emitting wildly varied slice durations but
the slices playing back in source order, the listener hears the
original audio with envelope fades at random points — which sounds
like a chopped-up version of the original, not chaos.

We considered three approaches:

1. **Force shuffle on internally when `resolution == "MAX RANDOM"`.**
   Tried first. Worked audibly but was opaque: the UI checkbox stayed
   unchecked while shuffle was actually happening. Users couldn't
   override even if they wanted "random durations, original order."

2. **Update the UI info text to suggest enabling shuffle for MAX
   RANDOM.** Conservative — preserves user control — but most users
   don't read info text and would hit the same "doesn't sound random"
   complaint.

3. **`.change()` handler that auto-checks the existing shuffle box
   when MAX RANDOM is selected, but lets the user manually uncheck.**
   Most "do what I mean" — visible state change in the UI, full user
   control preserved.

## Decision

**Approach #3.** Add a `resolution.change()` handler that:

- When `resolution == "MAX RANDOM"`: returns `gr.update(value=True)`
  for the `randomize_order` checkbox — user sees the box auto-check
  visibly.
- For any other resolution: returns `gr.update()` (no value, no-op)
  so the checkbox stays at whatever the user set it to.

```python
def _on_resolution_change(res):
    if res == "MAX RANDOM":
        return gr.update(value=True)
    return gr.update()  # leave the checkbox alone
resolution.change(
    fn=_on_resolution_change,
    inputs=resolution,
    outputs=randomize_order,
)
```

The `slurmify()` function itself just respects the checkbox uniformly
— no special-case override. The earlier internal-override
implementation was removed; shuffle behavior is now controlled
entirely by the visible UI state.

## Consequences

**Wins**

- **MAX RANDOM sounds random by default.** First-time users hear the
  intended chaos without having to know about the shuffle dependency.
- **State is visible.** When the box auto-checks, the user can see
  it happen — no hidden behavior.
- **User can still override.** Click MAX RANDOM, then manually uncheck
  shuffle → get random durations in source order. A legitimate creative
  mode (sounds like the original song with random fades, which is
  sometimes what you want).
- **No code-path divergence in `slurmify()`.** The DSP doesn't have
  to know about MAX RANDOM's UX semantics — it just reads the
  checkbox like any other parameter.

**Costs**

- **Tiny visible flash on resolution change.** When the user clicks
  MAX RANDOM, the box change fires, then the shuffle checkbox visibly
  ticks on. Cosmetic only.
- **Doesn't auto-uncheck on switching away from MAX RANDOM.** If user
  picks MAX RANDOM (shuffle auto-on), then picks 1/16, shuffle stays
  on. By design — assume the user wanted shuffle if they didn't manually
  turn it off. If they want it off, one click. (Auto-unchecking on
  switch-away would also be a hidden behavior surprise.)

## Risks

- **If the resolution changes via a side effect** (e.g. the
  `_randomize_all` button, which also picks a random resolution),
  the change handler fires correctly because it's listening to the
  Gradio `resolution.change()` event regardless of what triggered it.
  Verified by inspection — randomize-all sets `resolution` via the
  outputs dict, which fires `change` and the handler updates
  `randomize_order` accordingly.

## See also

- `app.py` `_on_resolution_change` and `resolution.change(...)` wiring
- `_randomize_all` — also returns `randomize_order` in its output dict;
  the value matches what the change handler would set, so they don't
  conflict
- ADR-0012 (trimodal distribution) — the upstream reason MAX RANDOM
  even matters
