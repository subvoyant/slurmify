# ADR-0010: Set the favicon via JS injection, not `head=` or `favicon_path`

- **Status:** Accepted
- **Date:** 2026-05 (v0.1.0)

## Context

We wanted the browser tab to show the Siena cat icon (the same image
already base64'd in `_ICON_B64` for the header) instead of the default
Gradio favicon (or no favicon at all).

We tried, in order:

1. **`<link rel="icon" href="data:image/png;base64,...">` injected via
   `launch(head=...)`.** No effect. The link tag appeared in the
   document `<head>` per DOM inspection, but the tab favicon stayed
   default. Suspected: Gradio writes its own favicon link AFTER
   `head=` content, winning precedence battles.
2. **`launch(favicon_path=temp_png_file)`.** The documented Gradio
   API. Gradio happily accepted the path, the file was readable at
   `/favicon.ico`, but the browser still showed the default. Suspected:
   browser favicon cache + Gradio's own favicon set in a `<link>` tag
   that's encountered earlier than our path-served one.
3. **`<link rel="shortcut icon">` legacy variant + `apple-touch-icon`
   variant alongside `<link rel="icon">`, all at the END of head.** No
   effect.
4. **JS injection that runs after page load** — purges any existing
   `<link rel*="icon">` elements and appends our own with a marker
   `data-slurm-fav` attribute so we don't purge ours on re-runs. Plus
   re-runs at 500ms / 2000ms / 5000ms after page load to defeat
   anything Gradio injects post-mount.

Approach #4 is the only one that consistently puts the cat in the tab.

## Decision

**Inject the favicon via JS that runs after page mount and re-applies
on a timeout schedule.** Keep the `<link>` tag in `head` AND the
`favicon_path` parameter as belt-and-suspenders fallbacks (they don't
hurt; some browsers in some configurations may honor them).

```python
_favicon_js = (
    '<script>\n'
    '(function () {\n'
    '    function _slurmSetFavicon() {\n'
    '        var d = document;\n'
    '        var olds = d.querySelectorAll(\'link[rel*="icon"]\');\n'
    '        for (var i = 0; i < olds.length; i++) {\n'
    '            if (!olds[i].dataset.slurmFav) olds[i].parentNode.removeChild(olds[i]);\n'
    '        }\n'
    '        var l = d.createElement("link");\n'
    '        l.rel = "icon";\n'
    '        l.type = "image/png";\n'
    '        l.dataset.slurmFav = "1";\n'
    f'        l.href = "data:image/png;base64,{_ICON_B64}";\n'
    '        d.head.appendChild(l);\n'
    '        console.log("[slurm] favicon set via JS at " + Date.now());\n'
    '    }\n'
    '    if (document.readyState === "loading") {\n'
    '        document.addEventListener("DOMContentLoaded", _slurmSetFavicon);\n'
    '    } else {\n'
    '        _slurmSetFavicon();\n'
    '    }\n'
    '    setTimeout(_slurmSetFavicon, 500);\n'
    '    setTimeout(_slurmSetFavicon, 2000);\n'
    '    setTimeout(_slurmSetFavicon, 5000);\n'
    '})();\n'
    '</script>'
)
```

The `data-slurm-fav="1"` marker is the key safety hatch: when the
function re-runs to defeat a late Gradio injection, it removes only
foreign `<link rel*="icon">` elements, leaving our own in place.

## Consequences

**Wins**

- **The favicon actually appears.** Across Chrome, Safari, Firefox.
- **Survives Gradio's runtime favicon manipulation** — the timed
  re-runs catch anything Gradio injects after our initial run.
- **Browser cache no longer matters as much** — even if the browser
  cached the old favicon, our JS forcibly inserts a fresh `<link>`
  with the data-URL on every page load.

**Costs**

- **Three setTimeout calls** running on every page load — minor
  console noise (`[slurm] favicon set via JS at <timestamp>` printed
  3-4 times). Helpful for debugging.
- **Brief flash possible** — if Gradio sets a favicon between page
  load and our 500ms first re-run, the user might see Gradio's
  default for a fraction of a second. In practice not noticed.
- **Browser favicon caching is still aggressive on the *outer*
  level** — even with our inserted link, some browsers cache the tab
  icon for the URL and won't refresh until hard-reload. Documented
  in beta-test notes.

## Risks

- **Future Gradio versions might fight back harder** with their own
  MutationObserver re-asserting their favicon. If that happens, the
  fix is to add our own MutationObserver watching for foreign
  `<link rel*="icon">` insertions and removing them.
- **CSP changes** — if a future deployment runs Slurmify behind a
  strict Content-Security-Policy that bans `data:` URLs in `link`
  href, the JS injection breaks. Workaround would be to serve the
  PNG at a real URL via Gradio's static file route.

## See also

- `app.py` `_favicon_js` block in the `__main__` section
- `_ICON_B64` for the source image (also used in the header)
- ADR-0004 (head injection rationale) — the related but different
  problem of injecting INIT_JS, where head injection DOES work
