# ADR-0003: FX chain binds to a dedicated `<audio>` element exactly once

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

The Web Audio FX chain (distortion → ring mod → delay → phaser) has to
be wired to *some* HTML `<audio>` element so that audio playing
through it is processed. The obvious candidate is the `<audio>` inside
Gradio's `gr.Audio` output component.

Two W3C-spec constraints break the obvious approach:

1. **`AudioContext.createMediaElementSource(el)` may be called at most
   once per `HTMLMediaElement` for the lifetime of that element.**
   Closing the AudioContext does NOT release the binding. A second
   call throws `InvalidStateError`. ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/createMediaElementSource))
2. **An AudioContext starts in `suspended` state and can only be
   resumed during a real user gesture.** A `setInterval` callback or
   `onload` handler is *not* a user gesture and `resume()` rejects
   silently from those contexts. ([Chrome](https://developer.chrome.com/blog/web-audio-autoplay))

Earlier code re-bound the FX chain on every src change to Gradio's
`<audio>`. First run worked; second run threw `InvalidStateError`,
silently swallowed by a try/catch, and the element was now stuck
talking to a closed context — total silence.

## Decision

1. **We own a dedicated `<audio id="slurm-fx-audio">`** declared as a
   `gr.HTML` block inside the FX panel. Gradio doesn't render it, so
   it isn't part of WaveSurfer's lifecycle.
2. **`_fxSetup()` is idempotent.** First line: `if (_fxCtx) return;`.
   `createMediaElementSource(audioEl)` is called exactly once for the
   life of the page.
3. **Gradio's slurm-output URL is mirrored into our element.** Two
   parallel mechanisms:
   - `audio_out.change(fn=None, js=...)` — fires on Gradio's value
     changes.
   - A 400 ms polling loop walking shadow DOM under
     `#slurm-audio-out` — backup, since `change` timing under
     WaveSurfer can race with mount.
4. **Resume on user gesture.** `_fxSetup` adds a `play` event listener
   on our `<audio>` that calls `_fxCtx.resume()`. The user pressing
   play *is* a real gesture; `resume()` succeeds in the same tick.

## Consequences

**Wins**

- No `InvalidStateError`, ever, regardless of how many times the user
  re-runs slurmify.
- AudioContext reliably reaches `running` state.
- New slurmify runs only update `fxAudio.src` — the chain itself never
  rebuilds.

**Costs**

- One extra `<audio>` element visible in the FX panel. Treated as a
  feature ("FX preview" with its own play controls).
- Two src-mirroring code paths instead of one. Belt and suspenders;
  acceptable because `change` is theoretically authoritative but
  WaveSurfer mount can race it.

## See also

- `app.py` `INIT_JS._fxSetup` — the `if (_fxCtx) return;` guard
- `app.py` `audio_out.change(fn=None, js=...)` handler
- `app.py` polling block (search for "FX: mirroring src")
- MDN — [createMediaElementSource](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/createMediaElementSource)
