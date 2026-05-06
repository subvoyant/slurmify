# ADR-0005: PyInstaller `optimize=0` is mandatory

- **Status:** Accepted
- **Date:** 2025

## Context

PyInstaller's `optimize=` knob (`0`/`1`/`2`) maps to Python's
`-O`/`-OO` flags — strip assertions, then strip docstrings, and write
optimized `.pyc` bytecode (`.pyo` historically).

Setting `optimize=2` is tempting: smaller bundle, slightly faster
import.

We tried it. The frozen `.app` reliably failed at launch with:

```
zlib.error: zlib header mismatch
```

… while importing one of librosa's lazy-loaded submodules. The error
originates from PyInstaller's bytecode loader trying to decompress a
`.pyo` chunk that was written by an unmatched optimizer pass relative
to the way the loader strips the `.pyo` magic header.

Several PyInstaller GitHub issues track variants of this. The
official guidance is "if you need lazy imports of complex packages
like librosa, scipy, gradio, leave optimize=0".

## Decision

**`optimize=0` in `slurmify.spec`. Annotated with a `# do NOT change`
comment.**

Do not flip it without an exhaustive smoke-test that exercises every
lazy-loaded path (FX preview, all output formats including ffmpeg
encode, video export, every skin).

## Consequences

**Wins**

- Reliable launches across all our ML/audio dependencies.
- Docstrings preserved, so `help()` and IDE introspection work in the
  bundle.

**Costs**

- Bundle is ~5–10 % larger.
- Imports are negligibly slower (microseconds per module). Not
  user-visible.

## Risks

A future PyInstaller release may fix the underlying loader bug; if
that ships, the optimize knob becomes safe again. Until proven on a
clean machine, leave it at 0.

## See also

- `slurmify.spec` — `optimize=0` line
- PyInstaller [issue #6537](https://github.com/pyinstaller/pyinstaller/issues/6537) and friends (zlib header mismatch family)
