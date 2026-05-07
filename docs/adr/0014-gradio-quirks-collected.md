# ADR-0014: Collected Gradio behavior quirks (catalog of "don't waste time on this again")

- **Status:** Accepted (living document)
- **Date:** 2026-05 (consolidated during v0.1.0 / v0.1.1 work)

## Context

Building Slurmify against Gradio 5+/6.x, we hit a series of behaviors
that aren't documented (or are documented misleadingly) and that each
took non-trivial debugging to figure out. This ADR collects them in
one place so future contributors / agents can recognize the pattern
and not waste time re-discovering the same thing.

The other Gradio-specific ADRs in this folder (0003, 0004) cover
single load-bearing decisions in detail. This ADR is the catalog of
smaller ones that don't each warrant their own page.

## Catalog

### 1. `gr.Audio` MIME validation is server-side and unbypassable

The component's frontend file picker uses `accept="audio/*"`, but
that's just the surface. The backend ALSO validates MIME types
against a hardcoded whitelist (`audio/aac, audio/mpeg, audio/wav,
audio/x-wav, audio/opus, audio/webm, audio/flac, audio/vnd.rn-
realaudio, audio/x-ms-wma, audio/x-aiff, audio/amr, audio/*`).
Stripping `accept` via JS only fools the file picker; the server
still rejects video uploads.

**If you need to accept video/any-file on an audio-related upload
zone:** use `gr.File(file_types=None)` and route via a change handler.
See ADR-0009.

### 2. `gr.Audio(interactive=False)` removes the playback transport

The docs imply `interactive` only controls upload-vs-display. It
also removes the play/pause/skip controls. If you want a display-
only audio component (no upload UI) but with playback transport,
there's no built-in way — you have to either keep `interactive=True`
and hide the upload UI via CSS, or use `visible=False` until the
component has a value (then `gr.update(visible=True)` to reveal it).

### 3. `<link rel="icon">` injected via `head=` is overridden at runtime

Gradio writes its own favicon link AFTER `head=` content. Same for
the `favicon_path` parameter — works as a server route but the
browser still picks up Gradio's later-injected link first.

**The only reliable fix: JS injection that runs after page mount and
re-applies on a timeout.** See ADR-0010.

### 4. Gradio Dropdown's white background lives on `.wrap-inner`

Base CSS rules on `select`/`input` don't reach the visible value-
display element of the modern Dropdown. Set `elem_classes=
["my-dropdown"]` and target `.my-dropdown, .my-dropdown *` with
the universal selector to force theming everywhere. The popup
options list is rendered into `document.body` (outside the
component wrapper), so target `body > ul[role="listbox"]` and
`body > .options` separately.

### 5. `gr.Textbox` renders labels TWO ways

- **Without `info=`:** bare `<label>` element, browser default size
  (visually large, distinct font feel).
- **With `info=`:** `<div class="label-wrap"><span>...</span></div>
  <div class="info">...</div>` — compact label + subtitle.

If two adjacent Textboxes have different `info=` configurations,
their labels look dramatically different. Either give them ALL info
(or all none), or write CSS that targets both DOM patterns:

```css
#my-box label, #my-box .label-wrap > span {
    font-size: 0.75rem !important;
    /* ... */
}
```

### 6. `:focus-within` on blocks recolors border AND label

Gradio's default theme highlights the entire block (border +
internal label color) when any input inside has focus, using
`var(--border-color-accent)`. If your accent color is dramatic
(cyan, in our case), focus state is visually loud and makes
identical components look mismatched depending on which is focused.

Override with:
```css
.gradio-container .block:focus-within {
    border-color: <default-border-color> !important;
}
.gradio-container .block:focus-within .label-wrap > span {
    color: <default-label-color> !important;
}
```

### 7. `.then()` chains break on `gr.Error`

`go_btn.click(fn=A).then(fn=B).then(fn=C)` — if A raises `gr.Error`,
B and C never run. This caused our "dancer stays visible after
validation error" bug: the show-dancer step ran, the process step
errored, the hide-dancer step never fired.

Fixes (any of):
- Validate BEFORE the show step (move validation to a pre-step that
  raises on bad input, runs first; only then trigger the show)
- Use a generator function that yields show-state, runs work in a
  try/finally, yields hide-state in finally before re-raising
- Combine all states into a single fn that returns dict updates for
  multiple components

### 8. Single Textbox values can render multi-line by default

Without `max_lines=1`, `gr.Textbox` may render as a `<textarea>`
that's taller than expected — particularly visible when laid out
next to single-line inputs. Always set `max_lines=1` for inputs
intended as single-line.

### 9. Audio elements live inside Shadow DOM (WaveSurfer)

`document.querySelectorAll('audio')` does NOT find Gradio Audio's
playback element — it's wrapped by WaveSurfer in a Shadow DOM tree.
Need a recursive walker that descends into `el.shadowRoot`. See
`_fxWalk` in INIT_JS and ADR-0003.

### 10. `gr.update()` with no args is a no-op (preserves current value)

Useful in change handlers that want to update some outputs and leave
others alone:

```python
def handler(input_value):
    if input_value == "MAX RANDOM":
        return gr.update(value=True)  # update this output
    return gr.update()  # no-op, leave current value
```

### 11. CSS `:has()` selector works in modern browsers but is fragile against Gradio's class names

`.slurm-audio:not(:has(.waveform-container))` works for *some*
Gradio versions and breaks in others, because Gradio's actual class
names for the loaded-state element vary. Prefer unconditional sizing
or universal-descendant selectors when the dynamic state isn't
exposed via a stable class name.

### 13. `gr.Accordion(open=False)` does NOT render children in the DOM (Gradio 5+)

Gradio 5 uses Svelte's `{#if}` semantics for accordion content.
When `open=False`, the accordion's children are **completely absent
from the DOM** — not hidden, not `display:none`, just not there.
Opening the accordion causes Svelte to mount the children fresh.

This affects any JS that looks for elements inside a closed accordion
at page load (e.g. `document.getElementById('slurm-fx-audio')`).
That query returns `null` until the user first opens the accordion.

Our FX chain handles this with a 400 ms `setInterval` backup that
polls for `#slurm-fx-audio` and activates as soon as it appears.
The `audio_out.change` JS path logs "FX preview element not found"
when the accordion is closed — that is **expected and handled**, not
a bug. The `_fxBindPoll` 200 ms loop separately waits for the element
before binding the `play` event listener.

**If you add any component inside a closed accordion that JS needs at
startup:** move it outside the accordion, or rely on polling rather
than a one-shot `getElementById` at init time.

*(Observed against Gradio 5 / 6.x, 2026-05)*

### 12. `elem_classes=[...]` is the most reliable styling hook

Gradio's auto-generated class names (Svelte hashes, etc.) can change
between versions. `elem_classes=` adds your own class to the rendered
component and is stable. Pattern:

```python
my_widget = gr.SomeComponent(..., elem_classes=["slurm-foo"])
```

```css
.slurm-foo, .slurm-foo * {
    /* style aggressively — universal selector covers internal divs */
}
```

## Decision

**Treat this catalog as the first thing to check when something
"weird" is happening with a Gradio component.** Update the catalog
when a new quirk is discovered.

## Consequences

**Wins**
- Future debugging starts from a known-quirks list rather than from
  scratch.
- Patterns that work (elem_classes + universal selector, JS-after-
  mount for favicon, etc.) are documented as patterns, not just
  solutions to one-off problems.

**Costs**
- Living document — needs to be updated. Gradio releases can change
  behavior; old quirks may stop applying and new ones appear.

## Risks

- Gradio's behavior IS version-dependent. If Slurmify upgrades
  Gradio, half this list may become wrong. Re-test before relying.
  Date-stamp new entries when added so we know what version they
  were observed against.

## See also

- ADR-0003 — `createMediaElementSource` once + Shadow DOM walker
- ADR-0004 — Why `head=` works for INIT_JS but not for favicons
- ADR-0009 — Universal upload via `gr.File`
- ADR-0010 — Favicon via JS injection
