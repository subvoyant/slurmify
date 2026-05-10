# ADR-0023: Bundle ffmpeg + rubberband CLIs into the sidecar at `_MEIPASS` root

- **Status:** Accepted
- **Date:** 2026-05-09 (v0.2.0.x)

## Context

Slurmify's DSP pipeline shells out to two external CLI binaries:

- **ffmpeg** — used by `librosa`'s `audioread` fallback decoder for
  AAC/M4A/MP4/Opus, and by `src-python/api/upload.py` for video→audio
  extraction.
- **rubberband** — invoked via the `pyrubberband` Python wrapper, used
  by `slurmcore.slurmify()` for time-stretching and pitch-shifting.
  `pyrubberband/pyrb.py` calls `subprocess.check_call(['rubberband', …])`
  with no shell, no hardcoded path; it relies on PATH resolution. (Note:
  the runtime error message — *"Failed to execute rubberband. Please
  verify that rubberband-cli is installed."* — refers to the CLI as
  *rubberband-cli*, but the binary it actually invokes is named
  `rubberband`. Homebrew's `brew install rubberband` ships both names
  from one formula, but the canonical bare name is `rubberband`.)

In v0.1.x, both binaries were bundled into the `.app`'s `bin/` subdir
via `slurmify.spec`, and `app.py`'s bootstrap code prepended that
subdir to `PATH` on startup. That wiring is documented at the top of
the v0.1.x `app.py` ("PyInstaller bundle bootstrap") and was found by
both audioread and pyrubberband.

In v0.2.0, the architecture changed (Tauri shell + FastAPI sidecar)
and the bundling pattern needed to change with it:

1. The sidecar is built with PyInstaller in **onefile** mode (forced
   by Tauri's `externalBin` contract — see ADR-0022). On launch, the
   bootloader extracts the bundle to `sys._MEIPASS` (a temp dir like
   `/var/folders/…/T/_MEI<hash>/`).
2. `src-python/server.py` already prepends `sys._MEIPASS` to `PATH`
   on startup so audioread can find ffmpeg without a `bin/` subdir.

The original v0.2.0 spec correctly handled ffmpeg this way, but
**forgot to bundle rubberband at all**. Testers got a slurmify
RuntimeError on every input file. (See git history for the regression
window.)

## Decision

**Bundle every external CLI the sidecar shells out to at the
`_MEIPASS` root (dst `"."`), and rely on `server.py`'s existing PATH
prepend to make them resolvable.** Fail the build loudly if any
required CLI is missing on the build host — the bundle is broken
without them, and a missing-binary error at build time is far cheaper
to debug than a RuntimeError on a tester's machine after a
2 GB DMG round-trip.

```python
# In src-python/slurmify-backend.spec — applies symmetrically to
# every CLI we shell out to.
import shutil as _shutil

for cli_name in ("ffmpeg", "rubberband"):
    path = _shutil.which(cli_name)
    if not path:
        raise SystemExit(
            f"[slurmify-spec] ERROR: {cli_name} not found on PATH at "
            f"build time.\n  Install it before running build-sidecar.sh:\n"
            f"    brew install {cli_name}"
        )
    print(f"[slurmify-spec] bundling {cli_name} from {path}")
    binaries.append((path, "."))
```

(In the actual spec the two `which` calls are written out separately
so each error message can be customised — the `rubberband` failure
mode in particular benefits from explaining the binary-name vs
formula-name confusion. The pattern is the same.)

PyInstaller's macOS binary analyzer (`otool`) walks each CLI's dylib
dependency tree automatically and copies the linked dylibs alongside
the binary into the bundle. No separate `collect_dynamic_libs("…")`
call is needed for either CLI. (For `librubberband.<n>.dylib` and its
transitive deps like libsamplerate, this just works on the
M-series Homebrew install we tested with.)

## Consequences

**Wins**

- Symmetry with ffmpeg, which has been working since v0.2.0 ship.
  Future CLIs added to the pipeline follow the same one-line pattern.
- No `bin/` subdir gymnastics — the existing `_MEIPASS` PATH prepend
  in `server.py` does all the work.
- Build-time `SystemExit` if a required CLI is missing means we can
  never silently ship a broken bundle. (The original v0.2.0
  rubberband regression escaped because the spec didn't even *try* to
  find it; restoring the missing `which` check closes that hole.)

**Costs**

- Every CLI we add inflates the bundle size — `rubberband` plus its
  linked dylibs is on the order of a few MB on Apple Silicon, which
  is fine. If we ever need to bundle something heavier (sox, a full
  scientific stack), revisit.
- The build host needs `brew install ffmpeg rubberband` (and the
  equivalent for any future CLI). The error messages tell users
  exactly what to run, so the cost is one-time per machine.
- Onefile bundles re-extract on every cold start (3–5 s on an M-series
  laptop). Adding more bundled binaries doesn't change the cold-start
  shape — they all extract together — but it does grow the temp
  footprint inside `_MEIPASS`. Not a concern at current sizes.

## Risks

- **`pyrubberband`'s misleading error wording**. The Python error
  reads "Please verify that rubberband-cli is installed" but the
  binary it looks for on PATH is named `rubberband`. If a future
  packaging change splits these (Homebrew has historically shipped
  `rubberband` and `rubberband-cli` as the same binary, but a future
  rename is conceivable), our `_shutil.which("rubberband")` would
  silently fail to find a binary that was actually installed. If you
  ever see this regress, also check `_shutil.which("rubberband-cli")`
  as a fallback.
- **macOS dylib relocation**. PyInstaller's analyzer copies linked
  dylibs alongside the binary, but the rpaths inside the binary still
  reference Homebrew install paths (e.g. `/opt/homebrew/lib/`). On a
  user's machine without Homebrew, those rpath lookups would fall
  through to the bundled-alongside dylib via macOS's standard search
  order — but if Apple ever tightens dyld in a way that changes
  fallback behaviour, this could regress. Mitigation: spot-check the
  bundle on a clean Mac (no Homebrew) before each release.
- **No automated check that the bundled CLIs *actually run* on a
  clean machine**. The build only checks they're present at build
  time; the smoketest at `src-python/scripts/smoketest.sh` runs the
  *unbundled* sidecar (which trivially has rubberband on its dev
  PATH). A real end-to-end test would launch the bundled DMG, drop a
  file in, and verify slurmify completes. Today that's a manual step.

## See also

- `src-python/slurmify-backend.spec` — the binaries block + the two
  build-time `which` checks
- `src-python/server.py` — the `sys._MEIPASS` PATH bootstrap that
  makes both CLIs resolvable at runtime
- `slurmify.spec` (v0.1.x vestigial) — original `find_bin("rubberband")`
  + `(rubberband_bin, "bin")` pattern that this ADR replaces
- ADR-0022 — Tauri 2 + sidecar architecture (explains why the v0.2.0
  bundle is onefile, why server.py is the PATH bootstrap point, etc.)
