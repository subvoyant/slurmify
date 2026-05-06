# ADR-0007: Pluggable skins via `body[data-skin]`

- **Status:** Accepted
- **Date:** 2026-05-04

## Context

We wanted to offer multiple visual treatments — the original
"subvoyant default", the psychedelic "Acid Cathedral", and the
skeuomorphic "Hardware Rack" — and let the user switch between them.

Three implementation paths:

1. **Per-skin Python launches.** Pick a skin from an env var or CLI
   flag; `ui.launch(css=...)` with that skin's CSS. *Cost:* user has
   to restart to switch.
2. **CSS file swap via JS.** On switch, replace the `<link>` tag's
   `href`. *Cost:* network fetch on every switch, asset pipeline
   needed to expose multiple CSS files.
3. **All skins coexist in one CSS string, scoped by an attribute.**
   Switch is just changing the attribute. *Cost:* slightly larger
   single CSS string.

## Decision

**All three skins live in `CUSTOM_CSS`. The active skin is the value
of `document.body.dataset.skin`. Selectors are scoped:**

```css
body[data-skin="acid"]    .gradio-container .block { ... }
body[data-skin="hardware"] .gradio-container .block { ... }
```

The default skin uses un-prefixed selectors that the original
Subvoyant theme already had. Acid and Hardware rules override them
when their `data-skin` is active.

INIT_JS, on load:

1. Reads `?skin=` from the URL.
2. Falls back to `localStorage.getItem('slurm_skin')`.
3. Falls back to `'default'`.
4. Whitelists against `_SKIN_NAMES` so an unknown value can't escape.
5. Writes the result to `document.body.dataset.skin` and back to
   localStorage.

A `<select id="slurm-skin-picker">` in the header `gr.HTML` block
calls `window.slurmSetSkin(value)` on change — instant, no reload.

## Consequences

**Wins**

- Switching is instant.
- Persistent per-user via localStorage.
- URL-based override (`?skin=acid`) works for sharing or testing.
- Adding a fourth skin = one new CSS block + one entry in
  `_SKIN_NAMES` + one `<option>` in the picker.
- Works without any backend change — pure browser state.

**Costs**

- `CUSTOM_CSS` grows with each skin. Currently ~25 KB total.
  Acceptable; the file is text and gzip handles it.
- Audio-reactive elements (VU meter for hardware, halo for acid) are
  always in the DOM but hidden by CSS `display: none` per skin. The
  rAF viz loop runs unconditionally and skips its expensive paths
  when the relevant skin isn't active — measured cost ~12 µs per
  frame, no impact at 60 fps.

## See also

- `app.py` `INIT_JS` — `_slurmInitSkin()`, `window.slurmSetSkin`
- `app.py` `CUSTOM_CSS` — the three skin sections
- `app.py` `gr.HTML` blocks — `<select id="slurm-skin-picker">`,
  `<canvas id="slurm-vu-meter">`, `<div id="slurm-go-halo">`
- ADR-0004 — INIT_JS injection mechanism this depends on
