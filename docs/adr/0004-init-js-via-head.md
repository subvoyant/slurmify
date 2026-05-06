# ADR-0004: Inject INIT_JS via `launch(head=...)`, not `gr.Blocks(js=)`

- **Status:** Accepted
- **Date:** 2026-04 (Gradio 6 upgrade)

## Context

Gradio offers three places to put browser-side JavaScript:

1. `gr.Blocks(js=...)` — passes a string to the Svelte frontend, which
   `eval()`-s it.
2. `ui.launch(js=...)` — same mechanism, different injection point.
3. `<script>` inside a `gr.HTML(...)` block — innerHTML injection.
4. `ui.launch(head="<script>...</script>")` — raw HTML appended to
   `<head>` of the served page.

Slurmify's INIT_JS is ~700 lines wrapped in an IIFE
`(function(){ ... })()` so it doesn't pollute the global scope.

We discovered through painful trial that on Gradio 6.x:

- `gr.Blocks(js=...)` and `launch(js=...)` use `eval()` and tolerate a
  single arrow-function expression but **break on IIFEs in some patch
  releases**. The page silently freezes on "Loading…" with no console
  error.
- `<script>` tags inside `gr.HTML` are subject to **modern browsers'
  innerHTML script-execution policy** — they're parsed but never
  executed.
- `head=` injects literal HTML into `<head>`. The browser parses the
  `<script>` tag the normal way; the IIFE runs as expected.

## Decision

**Build INIT_JS as a Python multi-line string. Inject via
`ui.launch(head=f"<script>\n{INIT_JS}\n</script>")`.**

We can prepend other `<head>` content (Google Fonts links for the
skin system) into the same string before `<script>`.

## Consequences

**Wins**

- Reliable across Gradio 6.x patch releases.
- Standard browser script execution semantics — no `eval()` quirks.
- We can use IIFEs, ES6 features, and `let`/`const` without worrying.
- Scripts run before Gradio's frontend mounts most components, so the
  skin switcher applies `body[data-skin]` before paint.

**Costs**

- INIT_JS is one big Python string. CSS is the same — both lose IDE
  syntax highlighting. Mitigated by external editing in a `.js` /
  `.css` scratch file when doing heavy work.

## Risks

- A future Gradio release might restrict what `head=` accepts (e.g.
  CSP changes). If that happens, fallback options in order:
  1. Save INIT_JS to `assets/init.js` and inject `<script src="...">`
     via `head=` (still raw HTML).
  2. Bundle a tiny FastAPI mount-point that serves `init.js` at a
     known path, embed via `head=` with a relative URL.

## See also

- `app.py` `__main__` block — `_head` / `_fonts` construction
- ADR-0007 (skin system) — depends on INIT_JS reliably running on load
