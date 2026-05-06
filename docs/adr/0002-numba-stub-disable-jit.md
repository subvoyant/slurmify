# ADR-0002: Numba stub + `NUMBA_DISABLE_JIT=1` instead of bundling LLVM

- **Status:** Accepted
- **Date:** 2025

## Context

`librosa` optionally imports `numba` to JIT-compile some inner loops.
When `numba` is present, librosa wraps the affected functions with
`@jit` decorators; when it's not, librosa already handles the
`ImportError` with a Python fallback. So `numba` is *optional* at the
algorithm level.

The problem is that `numba` itself depends on `llvmlite`, which
bundles a full LLVM build (~150 MB). Inside a PyInstaller `.app`, two
issues compound:

1. The bundle balloons by ~150 MB just to get JIT compilation that
   might not even fire.
2. `numba` does not work inside frozen bundles in the general case —
   it tries to AOT-cache compiled functions to a writable directory
   that doesn't exist in `Contents/Frameworks/`.

## Decision

- **Exclude `numba` and `llvmlite` from the bundle.** `slurmify.spec`
  lists `llvmlite` in `excludes=[]` and **does not** install real
  numba in the venv.
- **Ship a tiny stub** at `stubs/numba/__init__.py` that exposes
  pass-through `jit` / `njit` / `prange` decorators so librosa's
  imports resolve without errors.
- **Set `NUMBA_DISABLE_JIT=1`** in the bootstrap when running frozen.
  This is what real numba reads to disable JIT compilation; we mirror
  the same env var for consistency with code that may consult it.

## Consequences

**Wins**

- ~150 MB removed from the bundle.
- No risk of cache-directory failures inside the `.app`.
- librosa works unchanged — its own fallback paths run.

**Costs**

- DSP that *would* benefit from JIT runs in pure Python. In practice
  this hurts only one or two librosa internals (e.g. some onset
  detection helpers); slurmify already finishes in well under audio
  duration on modest hardware.

## Risks / how to know if this stops being right

- A future librosa version starts requiring numba (not just optionally
  importing it). At that point either:
  - revisit the bundle-size cost and ship real numba + llvmlite, or
  - pin librosa to the last version that treats numba as optional.
- A new heavy DSP step we add cares about JIT performance. Profile
  first; consider Cython / a hand-vectorised numpy rewrite before
  reintroducing numba.

## See also

- `stubs/numba/__init__.py`
- `slurmify.spec` — `excludes`, `pathex=["stubs"]`
- `app.py` bootstrap — `os.environ.setdefault("NUMBA_DISABLE_JIT", "1")`
