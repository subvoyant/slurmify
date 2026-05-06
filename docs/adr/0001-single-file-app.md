# ADR-0001: Single-file `app.py` design

- **Status:** Accepted
- **Date:** Project inception (2025)
- **Deciders:** Subvoyant

## Context

A typical Python web app of this size (~2 000 lines including embedded
JS and CSS) would normally be split across several modules — DSP in
one, UI in another, build helpers somewhere else, JS in `static/`,
CSS in `static/css/`, etc.

Two countervailing forces:

1. **PyInstaller analysis is fragile.** Static-import scanning misses
   dynamic imports inside lazy-loaded packages (librosa, scipy, gradio
   internals). Splitting the entry point into multiple modules
   multiplies the surfaces where `hiddenimports=` has to compensate.
2. **Browser-side code is tiny.** ~700 lines of JavaScript and ~1 000
   lines of CSS. Not enough to justify a separate frontend repo or
   bundler.

## Decision

Keep everything in one `app.py`. JS lives as a multiline Python string
named `INIT_JS`; CSS lives as a multiline string named `CUSTOM_CSS`;
all DSP, the FX baked-in implementations, the Gradio UI builder, and
`__main__` are in one file in that order.

Skill files (`stubs/numba/__init__.py`) and the PyInstaller spec are
the only siblings; everything else is `app.py`.

## Consequences

**Wins**

- One entry point — PyInstaller analysis is straightforward.
- Cmd+F across "the whole codebase" works.
- Easy for a contributor to read end-to-end in one sitting.
- Editing CSS or JS is a Python edit; no separate build step or
  hot-reload server.

**Costs**

- File is large; new contributors might be intimidated. Mitigated by
  the section signpost comments (`# ── name ───`) and the
  `AGENT_DIGEST.md` map at the repo root.
- Any IDE feature that scopes to a "module" is doing it on the whole
  app at once.
- Tests would be awkward — there are none currently; this would be
  the time to introduce a `slurmify_core/` package if we did.

## When to revisit

When automated tests are introduced, or if the file approaches
~3 000 lines with multiple loosely-related subsystems. At that point
the natural split would be `slurmify/audio.py`, `slurmify/fx.py`,
`slurmify/video.py`, `slurmify/ui.py`, with `app.py` as the
PyInstaller entry that imports them.
