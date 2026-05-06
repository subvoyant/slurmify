"""
Minimal numba stub for PyInstaller bundles.

librosa optionally imports numba for JIT-compiled filter implementations.
When NUMBA_DISABLE_JIT=1 is set (which we set in our bundle bootstrap),
numba normally replaces @jit/@njit with no-op pass-through decorators.
This stub replicates that behaviour so librosa can import numba without
the real package (and its huge llvmlite dependency) being present.
"""

from __future__ import annotations
import functools
import os

# ── decorator factories ────────────────────────────────────────────────────────

def _passthrough_decorator(*args, **kwargs):
    """Return a decorator that returns the original function unchanged."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*a, **kw):
            return func(*a, **kw)
        return wrapper
    # Support both @jit and @jit(...) usage
    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator

jit     = _passthrough_decorator
njit    = _passthrough_decorator
stencil = _passthrough_decorator

def vectorize(*args, **kwargs):
    def decorator(func):
        import numpy as np
        return np.vectorize(func)
    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator

def guvectorize(*args, **kwargs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*a, **kw):
            return func(*a, **kw)
        return wrapper
    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator

# ── type aliases (used in signatures) ─────────────────────────────────────────

float32  = "float32"
float64  = "float64"
int32    = "int32"
int64    = "int64"
uint8    = "uint8"
uint32   = "uint32"
uint64   = "uint64"
boolean  = "boolean"
complex64  = "complex64"
complex128 = "complex128"

class types:
    float32   = "float32"
    float64   = "float64"
    int32     = "int32"
    int64     = "int64"
    uint8     = "uint8"
    uint32    = "uint32"
    uint64    = "uint64"
    boolean   = "boolean"
    complex64 = "complex64"
    complex128 = "complex128"
    UniTuple  = tuple
    Array     = list

# ── typed containers (rarely used by librosa, but referenced) ─────────────────

class typed:
    class List(list):
        pass
    class Dict(dict):
        pass

# ── misc attrs that librosa or its deps may probe ─────────────────────────────

__version__ = "0.0.0+stub"
config = {}

def prange(*args, **kwargs):
    return range(*args)

def literally(x):
    return x
