# ADR-0024: Bundle project `assets/` into the sidecar via the spec's `datas` list

- **Status:** Accepted
- **Date:** 2026-05-09 (v0.2.0.x)

## Context

The sidecar's render-video pipeline (`src-python/api/render.py`)
stream-copies a pre-encoded loop MP4 from the project-root `assets/`
folder (per ADR-0006). The path is resolved through
`slurmio._asset("assets/siebaSlurm_A003.mp4")`, which:

- in dev mode returns `<repo_root>/assets/siebaSlurm_A003.mp4`
  (relative to the source file's directory), and
- in a frozen PyInstaller bundle returns
  `<sys._MEIPASS>/assets/siebaSlurm_A003.mp4` (relative to the
  bootloader's extraction directory).

PyInstaller does not copy arbitrary project files into `_MEIPASS` on
its own — only modules its analysis chases through and items
explicitly listed in the spec's `datas` argument get bundled. The
original v0.2.0 spec listed package metadata (`copy_metadata`) and
upstream library data trees (`collect_data_files`) but did not
include the project's own `assets/` folder.

Symptom in production: tester clicked **render YouTube MP4** in the
v0.2.0 DMG and got

```
render-video failed: FileNotFoundError: Missing animation loop
— assets/siebaSlurm_A003.mp4 not found.
```

`strings` on the bundled binary confirms `siebaSlurm` and `assets/`
were not present anywhere in the image — PyInstaller had silently
dropped them.

This is the same shape of regression as ADR-0023 (forgetting to
bundle `rubberband`): a runtime-only dependency that PyInstaller's
static analyzer can't see, so it has to be enumerated by hand in the
spec — and the absence of a build-time guard means the failure
surfaces only when a tester clicks the relevant button.

## Decision

In `src-python/slurmify-backend.spec`, after the
`copy_metadata`/`collect_data_files` block:

1. Define `_REQUIRED_ASSETS` — the set of asset filenames the sidecar
   touches at runtime (currently `["siebaSlurm_A003.mp4"]`).
2. Assert each required asset exists at `<repo_root>/assets/<name>`
   on the build host. If any is missing, `raise SystemExit(...)` with
   a message that names the missing path, mirroring the
   ffmpeg/rubberband checks added in ADR-0023.
3. Walk `<repo_root>/assets/` and append every regular file (skipping
   `.DS_Store`) to `datas` as `(src_absolute, "assets")`. The second
   element of the tuple is the destination *directory* relative to
   the bundle root — so the file lands at `<_MEIPASS>/assets/<name>`,
   exactly where `slurmio._asset()` looks for it.
4. Print a `[slurmify-spec] bundling asset assets/<name>` line per
   file so the build log advertises what was copied.

Bundling the entire folder, not just `_REQUIRED_ASSETS`, is
deliberate: it costs ~2.5 MB total and means a future `_asset()`
caller against `assets/siena_dancer.gif` or `assets/subvoyant_bug.png`
Just Works without a separate spec change. The runtime guard list
captures only the files we actively rely on **today**, so a
file-removal regression still fails the build loudly.

## Consequences

### Positive

- **Render-video works in the bundled DMG.** No more
  `FileNotFoundError: Missing animation loop`.
- **Build fails loudly** if a required asset is removed or renamed
  on the build host, matching the posture of ADR-0023's
  ffmpeg/rubberband guards.
- **Future-proofed**: the whole `assets/` folder is in the bundle,
  so adding a new server-side render or preview that loads
  `assets/<thing>` doesn't need a parallel spec edit.
- **Discoverable in build output**: each bundled asset is printed,
  so a quick `./scripts/build-dmg.sh 2>&1 | grep "bundling asset"`
  confirms what shipped.

### Negative

- The `_REQUIRED_ASSETS` whitelist must be kept in sync with what the
  Python sidecar actually reads. Adding a new `_asset(...)` call site
  for a file the build host can't be assumed to have? Add it to
  `_REQUIRED_ASSETS`. Removing a render path? Remove the file from
  the list (or, more realistically, leave it — a still-present asset
  is never the source of a regression).
- Marginal bundle-size cost (~2.5 MB) from copying the dancer GIF
  and subvoyant bug PNG, which the React frontend already serves
  via Vite. Acceptable.

### Neutral

- The `assets/` folder is not gitignored, so it travels with the
  repo and any clone-and-build flow has the files available. Unlike
  `graphic/` (~5 GB AE/PSD sources, gitignored) the runtime assets
  are tracked.

## Alternatives considered

1. **Hard-code the loop MP4 inside `slurmcore.py` as a base64 blob.**
   Rejected: 600 KB of base64 in source is awful to read, version
   control is unhappy, and the file is already present at a
   reasonable path — we just need to tell PyInstaller about it.

2. **Read the loop MP4 from the working directory at runtime.**
   Rejected: the .app's working directory is not `<repo_root>` for
   end users; this would require adding install-time data files
   inside the .app's `Resources/`, which collides with how `_asset()`
   is designed (it points at `_MEIPASS`, not bundle resources).

3. **Add a `collect_data_files("slurmify_assets")` package.**
   Rejected: would force creating a Python package wrapping the
   media files, which is more ceremony than the problem warrants for
   three files.

## Verification

After applying this change and running `./scripts/build-dmg.sh`, the
build log shows `[slurmify-spec] bundling asset assets/siebaSlurm_A003.mp4`
(plus the dancer GIF and bug PNG). Verify the bundle contains them:

```bash
strings src-tauri/binaries/slurmify-backend-aarch64-apple-darwin \
  | grep -E 'assets/siebaSlurm|assets/siena_dancer'
```

The bundled MP4 path should show up in the binary's strings, and
clicking **render YouTube MP4** in the DMG produces a valid output
file with the expected loop animation.

## See also

- [ADR-0006](0006-loop-mp4-stream-copy.md) — why the loop is a
  pre-encoded MP4 and stream-copied (the *what* this ADR ensures
  ships).
- [ADR-0011](0011-session-scoped-temp-cleanup.md) — `slurmio` ownership
  of the temp dir lifecycle (where `_asset()` lives in
  `slurmio.py`).
- [ADR-0022](0022-tauri-react-migration.md) — the v0.2.0 architecture
  that introduced the sidecar bundle.
- [ADR-0023](0023-bundle-cli-binaries-in-sidecar.md) — same
  PyInstaller-can't-see-runtime-only-deps story applied to CLI
  binaries; this ADR extends the same posture to data files.
