# CLAUDE.md — Slurmify orientation for AI agents

> **🛑 READ `AGENT_DIGEST.md` BEFORE DOING ANYTHING ELSE.**
>
> The digest is a precomputed code map: section signposts, load-bearing
> identifiers, "where do I add X" recipes, and links to the ADRs that
> explain non-obvious decisions. Reading it first saves you a slow
> ramp-up across the Tauri shell + React frontend + FastAPI sidecar
> trio and tells you which corners of the code have ADR-protected
> invariants.
>
> When you change anything that the digest flags as load-bearing,
> consult the matching ADR in `docs/adr/` before editing. If you
> introduce a new non-obvious decision, **write a new ADR** as part of
> the same change.

This file is the operational top sheet: what's where, conventions to
respect, and the small set of mistakes that have a high blast radius
in this codebase. `TECHNICAL.md` has the comprehensive narrative
reference for humans (note: large portions of TECHNICAL.md are still
v0.1.x-era as of this writing — see ADR-0022 for the v0.2.0
architecture).

---

## What this project is

Slurmify is a **Tauri 2 desktop app** with a **React 19 + Vite + TypeScript**
frontend and a **FastAPI Python sidecar** that owns all the audio DSP.
It opens a native macOS window (no browser tab), the Rust shell launches
the sidecar at startup, and the React UI talks to it over localhost
HTTP + SSE. Distribution is a `.app` bundle inside a `.dmg`, built via
`scripts/build-dmg.sh`.

The DSP engine (`slurmcore.py`, `slurmio.py`) is unchanged from v0.1.6
— the rewrite was UI-only. Anything to do with slicing, time-stretch,
note-mode, stereo handling, MAX RANDOM, beat masks, or FX burning still
lives in those two files at the repo root.

**Current version: 0.2.1.** Source of truth is the `version` field in
`src-tauri/tauri.conf.json`; mirror it in `package.json` and
`src-python/pyproject.toml` on every bump.

For the full migration rationale (why we left Gradio, Tauri vs
alternatives, the discovery-file IPC contract), read
[ADR-0022](docs/adr/0022-tauri-react-migration.md).

---

## File map

### v0.2.0 active code

| Path | What it is |
|---|---|
| `src-tauri/src/lib.rs` | Tauri 2 Rust shell. Spawns the sidecar via tauri-plugin-shell, parses the JSON ready-line from sidecar stdout, exposes `read_backend_discovery` to JS, manages window lifecycle. |
| `src-tauri/src/main.rs` | Thin entry — calls `slurmify_lib::run()`. Don't put logic here. |
| `src-tauri/Cargo.toml` | Rust dependencies. |
| `src-tauri/tauri.conf.json` | App identity, window config, bundle targets, **canonical version field**, `externalBin` reference for the sidecar. |
| `src-tauri/entitlements.plist` | macOS hardened-runtime entitlements (network for localhost, JIT off, etc.). |
| `src-tauri/capabilities/` | Tauri 2 capability scopes (which permissions the JS side has — keep these tight). |
| `src-tauri/binaries/` | Drop folder for the PyInstaller sidecar. Populated by `scripts/build-sidecar.sh` to `slurmify-backend-<rust-target-triple>`. |
| `src/` | React frontend. Entry: `main.tsx` → `App.tsx`. |
| `src/components/` | UI components. shadcn/ui primitives in `src/components/ui/`. |
| `src/hooks/` | React hooks: `useFxChain`, `useSlurmifyJob`, `useRenderVideoJob`, `useBackendUrl`, `useSkinColors`. |
| `src/stores/` | Zustand stores for cross-component state: `fxStore`, `videoStore`, `uiPrefsStore`. |
| `src/lib/api.ts` | The HTTP/SSE client that talks to the sidecar. Read this BEFORE writing a new endpoint call. |
| `src/styles/globals.css` | Tailwind + custom CSS variables. Skin theming via CSS custom properties. |
| `tailwind.config.ts` | Tailwind config. |
| `package.json` | Frontend deps + scripts. `version` mirrors `tauri.conf.json`. |
| `vite.config.ts` | Vite dev server (port 1420). |
| `index.html` | HTML shell loaded into the WebView. |
| `src-python/server.py` | FastAPI sidecar entry. Picks a free port, writes a JSON discovery file, mounts route modules. |
| `src-python/api/` | One FastAPI router per concern: `upload.py`, `slurmify.py`, `fx.py`, `render.py`, `analyze.py`, `files.py`. |
| `src-python/jobs.py` | Job tracking + SSE progress streaming. Long-running DSP runs as background threads; HTTP returns immediately. |
| `src-python/slurmify-backend.spec` | PyInstaller spec for the sidecar. **`optimize=0` is mandatory** (ADR-0005 still applies). |
| `src-python/pyproject.toml` | Sidecar Python deps. |
| `slurmcore.py` | **Pure DSP** — slicing, stretching, FX, MAX RANDOM, note-mode, stereo handling. NumPy in/out, no I/O. Unchanged from v0.1.6. (ADR-0016) |
| `slurmio.py` | **Filesystem IO** — `load_audio`, `_write_audio`, session-scoped temp directory, `_new_temp_path`. Unchanged from v0.1.6. (ADR-0017) |
| `scripts/build-sidecar.sh` | (macOS/Linux) Runs PyInstaller against `slurmify-backend.spec`, places the binary at `src-tauri/binaries/slurmify-backend-<triple>`. |
| `scripts/build-dmg.sh` | (macOS) Full pipeline: clean → build sidecar → `pnpm tauri build` → sign → notarize → re-package DMG with versioned names + LICENSE + tester README + Applications symlink. Output: `SIENA Slurmer <version>.dmg`. |
| `scripts/build-sidecar.ps1` | (Windows) PowerShell mirror of `build-sidecar.sh`. Produces `slurmify-backend-x86_64-pc-windows-msvc.exe`. |
| `scripts/build-windows.ps1` | (Windows) Full pipeline: clean → build sidecar → `pnpm tauri build --bundles nsis` → NSIS installer. No code signing yet (see `docs/WINDOWS_BUILD.md` "What's deferred"). |
| `.github/workflows/windows-build.yml` | GitHub Actions workflow — triggers on `v*-win` tags or manual dispatch, runs the Windows pipeline on `windows-latest`, uploads the `-setup.exe` as a downloadable artifact. The "no Windows machine needed" path. |
| `assets/siebaSlurm_A003.mp4` | Pre-encoded loop animation for the YouTube MP4 export. Stream-copied via ffmpeg (ADR-0006 still applies). |
| `docs/TESTER_README.md` | Current macOS tester-facing handoff doc (Max). Bundled into the DMG. |
| `docs/TESTER_README_WINDOWS.md` | Windows tester-facing handoff doc (Bob). Sent alongside the NSIS `-setup.exe`. |
| `docs/WINDOWS_BUILD.md` | Strategy + step-by-step for the Windows build pipeline. Path A is GitHub Actions (no Windows machine needed); Path B is local Windows machine / VM. Read before changing the Windows scripts. |
| `docs/adr/` | Architecture Decision Records 0001–0022. **ADR-0022 is the v0.2.0 architecture spec.** |
| `LICENSE` | GPL-3.0 + third-party notices. Bundled into the DMG. |
| `README.md` | User-facing setup. |
| `TECHNICAL.md` | Long-form engineering reference. **Note: large portions are still v0.1.x-era — defer to ADR-0022 for v0.2.0 architecture and to AGENT_DIGEST.md for the current code map.** |
| `AGENT_DIGEST.md` | **Precomputed code map for agents — read first.** |
| `CLAUDE.md` | This file. |

### v0.1.x vestigial files (still in repo, NOT part of v0.2.0 runtime)

| Path | Status |
|---|---|
| `app.py` | Old Gradio bootstrap. Replaced by `src-python/server.py` + `src-tauri/`. Don't edit for v0.2.0+ work. |
| `slurm_ui.py` | Old Gradio UI orchestration. Replaced by `src/` (React). |
| `ui_assets.py` | Old INIT_JS + CUSTOM_CSS + base64 assets. Replaced by `src/` + `src/styles/`. |
| `build.sh` | Old PyInstaller-of-monolith pipeline. Replaced by `scripts/build-dmg.sh`. |
| `slurmify.spec` | Old PyInstaller spec for the monolith. Replaced by `src-python/slurmify-backend.spec`. |
| `entitlements.plist` (root) | Old entitlements file. Replaced by `src-tauri/entitlements.plist`. |
| `stubs/numba/` | Old numba shim — still potentially useful if PyInstaller analysis needs it for the sidecar; check `src-python/slurmify-backend.spec` to see whether it's referenced. |
| `requirements.txt` | Old top-level deps. Replaced by `src-python/pyproject.toml`. |
| `SLURMER_BETATEST_INSTRUCTIONS.md` | v0.1.x release notes. Not bundled into v0.2.0 DMGs — `docs/TESTER_README.md` is the new tester doc. |

These are kept as a reference for porting v0.1.x features (e.g.,
`INIT_JS` patterns when reimplementing the FX chain in React). Don't
delete them yet, but never edit them as if they were live.

---

## How to run / test / build

```bash
# ── Dev: run the frontend + sidecar separately ──
# Terminal 1 — Python sidecar (writes a discovery file the Rust shell reads)
source src-python/.venv/bin/activate
python src-python/server.py

# Terminal 2 — Tauri dev shell (Vite + Rust + WebView)
pnpm tauri dev

# ── Dev: frontend-only (browser, against an already-running sidecar) ──
pnpm dev
# → http://localhost:1420
# Note: many features assume native window context (Tauri commands).
# Frontend-only is OK for component work, not full integration.

# ── Type-check / lint ──
pnpm tsc -b --noEmit          # frontend
python3 -c "import ast; ast.parse(open('slurmcore.py').read())"  # DSP
python3 -c "import ast; ast.parse(open('slurmio.py').read())"

# ── Sidecar smoke test ──
src-python/scripts/smoketest.sh

# ── Full release build (sidecar → tauri → DMG, ~3-5 min) ──
./scripts/build-dmg.sh
# Output: src-tauri/target/release/bundle/dmg/SIENA Slurmer <version>.dmg

# ── Reuse an existing sidecar build (skip ~30 s) ──
SKIP_SIDECAR=1 ./scripts/build-dmg.sh
```

There are still **no automated tests** beyond the smoketest. Verify
manually: load a file → slurmify → play → twist FX → burn → render
video. Stereo + mono inputs both. Be especially watchful for v0.1.6
parity regressions, since the rewrite is only meant to swap the UI.

---

## Conventions

### Code style

- **Verbose comments and tooltips** — Slurmify's standing rule (see
  the user's `feedback_ground_rules` memory). Block headers use the
  `# ── name ───` Unicode-line style. Tooltips on every interactive
  control. Explain *why* in code comments, not just *what*.
- **Use `_asset(rel_path)`** in any Python code that needs a bundled
  resource (sidecar pyinstaller bundle uses `sys._MEIPASS`).
- **HTTP errors raise `HTTPException`** in FastAPI routes — anything
  else surfaces as a 500 with a stack trace. Match the conventions in
  the existing files in `src-python/api/`.
- **React state lives in Zustand stores** for anything cross-component
  (FX state, video render state, UI prefs); useState/useReducer for
  truly local state. Don't reach into another component's state via
  refs.

### Frontend ↔ sidecar boundary

The frontend talks to the sidecar over plain HTTP and SSE. Rules:

- **Long-running DSP jobs use the job pattern.** Frontend POSTs to
  `/slurmify` (or `/burn-fx`, `/render-video`), gets a `{job_id}`
  back, opens an SSE on `/jobs/{id}/progress`, and consumes
  `{progress, desc, done, output_id}` events until done. See
  `src-python/api/slurmify.py` for the canonical pattern;
  `src/hooks/useSlurmifyJob.ts` for the consumer.
- **Discovery is once, at app start.** The Rust shell writes the
  port to its store; React reads it via `read_backend_discovery`
  (Tauri command) on first mount and cached in `useBackendUrl`.
  Don't re-poll; the port is stable for the app lifetime.
- **Files are addressed by ID, not path.** Sidecar returns
  `{output_id}`; frontend GETs `/files/{output_id}` (with HTTP
  range support for the WaveformPlayer's seekable streaming).

### Python ↔ DSP boundary (slurmcore/slurmio purity rules)

- `slurmcore.py` — pure DSP. No `os`, `sys`, `soundfile`, `gradio`,
  `shutil`, `subprocess`, `fastapi` imports. NumPy in/out only. (ADR-0016)
- `slurmio.py` — filesystem IO only. May import `os`, `tempfile`,
  `shutil`, `subprocess` (for ffmpeg). May NOT import `fastapi`,
  `gradio`, or `tauri`. One lazy `import gradio as _gr` was the only
  exception in v0.1.x — that's gone now; slurmio is fully framework-
  agnostic in v0.2.0. (ADR-0017)
- The sidecar's API layer (`src-python/api/*.py`) is the boundary
  where these pure modules meet HTTP. Add request validation, file
  IO, and job orchestration there — not in `slurmcore.py`.

### Adding dependencies

- **Frontend (TypeScript/React):** `pnpm add <pkg>`. If it touches
  Tauri APIs, also check `src-tauri/capabilities/default.json` —
  Tauri 2 requires explicit capability grants for shell, fs, etc.
- **Sidecar (Python):** add to `src-python/pyproject.toml`. If it has
  dynamic imports (most things do): also add to the `hiddenimports`
  list in `src-python/slurmify-backend.spec`. If it ships data files
  (e.g., librosa fixtures): `collect_data_files("name")` in the spec.
  Then run `./scripts/build-sidecar.sh` and launch the smoketest to
  confirm.
- **Rust (Tauri shell):** `src-tauri/Cargo.toml`. Most plugins also
  need a capability grant. Cargo will rebuild on next `pnpm tauri
  dev`/`build`.

---

## Danger zones — read before touching

These are bugs that have either bitten us or are guaranteed to bite if
ignored. The full table with one-line warnings + ADR links lives in
`AGENT_DIGEST.md`; the top items, with extra context:

### v0.2.0-specific (Tauri sidecar / React)

1. **The sidecar discovery contract.** `src-python/server.py` writes a
   JSON file to the OS temp dir at startup containing
   `{port, pid, started_at}`; `src-tauri/src/lib.rs` reads it from
   Rust (not JS — see the comment in lib.rs for why JS reading would
   need overly broad fs scope). If you change the filename, format,
   or location on either side, change it on the other side in the
   same commit. (ADR-0022)
2. **`externalBin` only supports a single file, not a folder.** That
   is why the sidecar PyInstaller build is `--onefile` and pays a
   3–5 s self-extract on every launch. Don't switch to onedir
   without solving Tauri's resource-dir spawning first.
3. **`src-python/server.py` MUST print the ready-line BEFORE
   uvicorn.run()** — Tauri parses stdout looking for the
   `slurmify_ready` JSON line. Once uvicorn takes the foreground,
   stdout interleaves with request logs. Print first, then start the
   server.
4. **Tauri 2 capabilities are deny-by-default.** If JS suddenly fails
   to invoke a Rust command or use a plugin, check
   `src-tauri/capabilities/default.json` first. Don't grant broad
   scopes (like `fs:scope-temp-recursive`) — keep the surface tight.
5. **Build is signed + notarized via `scripts/build-dmg.sh` (ADR-0025).**
   Tauri's bundler signs the .app with `APPLE_SIGNING_IDENTITY` (resolved
   from the keychain), then we re-sign the externalBin sidecar with
   hardened runtime + entitlements (defensive workaround for tauri#11992),
   re-seal the .app, notarize via `xcrun notarytool` using a keychain
   profile (no plaintext password in source — see ADR-0025), and staple
   both the .app and the DMG. A fresh build host needs Xcode → Settings →
   Accounts to download the Developer ID Application cert AND a one-time
   `xcrun notarytool store-credentials slurmify-notary …` setup; the
   script bails with the exact command if the profile is missing. For
   local smoke-test builds where you don't want the 1–5 min notarization
   wait, run `SKIP_NOTARIZE=1 ./scripts/build-dmg.sh` — but never ship
   that DMG (Sequoia rejects it as "damaged"). (ADR-0025)
6. **Every external CLI the sidecar shells out to MUST be bundled in
   `slurmify-backend.spec`.** Today that's `ffmpeg` + `rubberband`
   (each appended to `binaries` at dst `"."` — see ADR-0023). If you
   add a new DSP path that calls another CLI (sox, lame, etc.), bundle
   it the same way and add a build-time `_shutil.which()` check so
   the build fails loudly when the host is missing it. Reason: the
   original v0.2.0 spec forgot rubberband; testers got
   "Failed to execute rubberband. Please verify that rubberband-cli is
   installed." on every slurmify call. Build hosts must have
   `brew install ffmpeg rubberband` before running build-sidecar.sh.
   (ADR-0023)
7. **Every project asset the sidecar reads at runtime MUST be
   enumerated in `slurmify-backend.spec`'s `datas` list.** PyInstaller
   doesn't auto-bundle the project-root `assets/` folder. The spec
   walks the folder into `datas` and asserts the files in
   `_REQUIRED_ASSETS` exist on the build host (matching the
   ffmpeg/rubberband posture from #6). If you add a new
   `slurmio._asset("assets/<thing>")` call site, append the filename
   to `_REQUIRED_ASSETS`. Reason: the original v0.2.0 spec didn't
   bundle `assets/` at all; render-video died with
   `FileNotFoundError: Missing animation loop —
   assets/siebaSlurm_A003.mp4 not found.` on every click. (ADR-0024)

### Carried forward from v0.1.x (still apply to the sidecar)

6. **`optimize=0` in `src-python/slurmify-backend.spec` is mandatory.**
   PyInstaller's bytecode optimisation breaks lazy-loaded modules with
   a "zlib header mismatch". Do not change. (ADR-0005)
7. **`hiddenimports` in the sidecar spec is intentionally long.**
   Don't trim speculatively. Add to it; remove only with a clean-
   machine smoke test.
8. **All sidecar temp files MUST go through `_new_temp_path()`.**
   Direct `tempfile.mkstemp()` calls leak to the system tmpdir
   forever and bypass the session cleanup. (ADR-0011)
9. **MAX RANDOM uses a TRIMODAL distribution, not log-uniform.**
   The bucket gaps (no 30-100ms or 500-1000ms slices) are the design,
   not an oversight. Filling them in destroys the audible chaos.
   (ADR-0012)
10. **Single-BPM rule for note-mode time params.** The four musical
    sliders (stutter skip, beat trim start/end, beat gap) can each be
    in "♪" mode. The note→ms conversion inside `slurmify()` MUST use
    the BPM returned by `detect_slice_points` — that's why that
    function returns `(positions, bpm)`. Don't recompute BPM
    elsewhere; don't decouple the slicer's tempo from the gap/trim
    tempo. (ADR-0020)
11. **Note-mode JS twin must match Python.** The note→ms grammar in
    the React frontend (look in `src/lib/` or wherever the live hint
    lives) MUST match `_note_to_ms` in `slurmcore.py`. Python is the
    source of truth for the slurm output; the JS exists only for the
    live "≈ NN ms @ BPM" hint. Change the grammar in one place →
    change it in the other in the same commit. (ADR-0020)
12. **Channel-layout boundary rule.** Slurmcore uses
    `(n_channels, n_samples)` (channels-first) for stereo. soundfile
    and pyrubberband both use `(n_samples, n_channels)`
    (channels-last). Transposes happen at the boundaries — `.T`
    before `_write_audio`, `_stereo_pyrb` around pyrb calls. NEVER
    assume `y` is 1-D inside slurmcore — use `_n_samples(y)` for
    the time-axis length and `y[..., a:b]` for time-axis slicing.
    (ADR-0021)
13. **Pass mono mixdowns to librosa beat/onset detection.**
    `librosa.beat.beat_track` and `librosa.onset.onset_detect`
    interpret 2-D input differently than our convention. Always
    feed them `_to_mono(y)`; the returned sample positions apply
    correctly to the original stereo array. (ADR-0021)

### Historical (v0.1.x only)

[ADR-0014](docs/adr/0014-gradio-quirks-collected.md) catalogs Gradio
5+/6.x oddities. Read it only if you're maintaining the v0.1.x branch
or porting an old behaviour and want to understand the original
constraint. The Gradio danger zones (createMediaElementSource one-shot,
INIT_JS injection, WaveSurfer shadow DOM, `gr.Audio` MIME validation,
favicon override, etc.) DO NOT APPLY to v0.2.0 work.

---

## Version-bump checklist

When the user asks to bump to version X.Y.Z, edit ALL of:

1. `src-tauri/tauri.conf.json` — `version` field (canonical source).
2. `package.json` — `version` field (must match).
3. `src-python/pyproject.toml` — `version` field (must match).
4. `src-python/api/__init__.py` or wherever `__version__` is referenced
   in the sidecar — keep in sync if it exists.
5. `docs/TESTER_README.md` — title and footer reference X.Y.Z; add a
   "What's new in X.Y.Z" section at the top.
6. `AGENT_DIGEST.md` — last-updated stamp at the bottom + the
   "Current version" reference near the top.
7. `TECHNICAL.md` — last-updated stamp at the bottom (note: most of
   this doc is still v0.1.x-era; only update the stamp until a real
   refresh).
8. `SLURMCORE_COMPARISON.md` — version stamp in the footer (the DSP
   content remains accurate).

Then verify no `X.Y.(Z-1)` references remain via:
```bash
grep -rn 'X\.Y\.(Z-1)' --include='*.json' --include='*.toml' \
    --include='*.ts' --include='*.tsx' --include='*.py' --include='*.md' . \
    | grep -v '/node_modules/' | grep -v '/target/' \
    | grep -v '/.venv/' | grep -v '/build/' | grep -v '/dist/'
```
The only remaining matches should be historical "What's new in X.Y.(Z-1)"
sections or migration-history references — those are intentional.

The DMG and `.app` filenames are auto-derived from the
`tauri.conf.json` version by `scripts/build-dmg.sh`; don't update
them separately.

---

## When asked to debug runtime issues

### Sidecar not launching / port not appearing

1. **Did Rust find the binary?** Check `src-tauri/binaries/` has
   `slurmify-backend-<rust-target-triple>` and is executable. If not,
   run `./scripts/build-sidecar.sh`.
2. **Is the discovery file being written?** Run the sidecar manually
   (`python src-python/server.py`) and check that it prints a
   `slurmify_ready` JSON line within ~1 s. Then check the OS temp
   dir for the discovery file.
3. **Is the Rust side reading from the right place?** `lib.rs` uses
   `std::env::temp_dir()`; on macOS this resolves the same as
   Python's `tempfile.gettempdir()`. If they don't match (rare —
   would mean different `TMPDIR` for the two processes), Tauri won't
   find the file.

### Frontend can't reach sidecar

1. **CORS.** `server.py` configures CORS for `tauri://localhost`
   (production) and `http://localhost:1420` (dev). If you've changed
   the Vite port, update CORS too.
2. **`useBackendUrl` returning a stale URL.** It reads from the
   Tauri command once on mount; if the sidecar was killed and
   relaunched on a new port, the cached URL is wrong. Restart the
   app, or add a re-read mechanism if this becomes a real workflow.

### DSP regression vs v0.1.6

The DSP code in `slurmcore.py`/`slurmio.py` is unchanged. If a
v0.1.6 behaviour is missing or different in v0.2.0, the regression is
almost certainly in the API layer (`src-python/api/*.py`) or the
React frontend — not in slurmcore. Compare the v0.2.0 request shape
to the v0.1.6 `process()` handler in the vestigial `slurm_ui.py`.

---

## Architecture decisions

Every decision that wasn't obvious — or that bit us once and shouldn't
be repeated — lives as an ADR in `docs/adr/`. Reading them is cheap
(each is ~1 page) and prevents revisiting solved problems.

When you make a non-obvious decision while editing this codebase,
write an ADR for it. The template is any existing file in
`docs/adr/`; the index is `docs/adr/README.md`. Keep the new ADR
linked from `AGENT_DIGEST.md`'s "danger zones" table if it touches a
load-bearing identifier.

If you find a constraint or quirk that isn't documented in an ADR,
that's a gap — file the ADR before someone else trips over it again.

## Pointers

- v0.2.0 architecture spec: [`docs/adr/0022-tauri-react-migration.md`](docs/adr/0022-tauri-react-migration.md)
- Comprehensive technical reference (mostly v0.1.x-era — flagged for refresh): `TECHNICAL.md`
- Architecture decisions index: `docs/adr/README.md`
- Code map for agents: `AGENT_DIGEST.md`
- User-facing setup: `README.md`
- Tester-facing handoff doc (Max): `docs/TESTER_README.md`
