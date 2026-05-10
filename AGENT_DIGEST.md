# AGENT_DIGEST.md — pre-computed code map for AI agents

> **You must read this file before doing anything else in this repo.**
> It saves you a slow ramp-up across the Tauri shell + React frontend
> + FastAPI sidecar trio and tells you where load-bearing decisions
> live.

This digest is anchored on **identifier names**, **file paths** and
**unique comment markers**, not line numbers (which shift with
edits). When you grep, use the comment markers and identifier names
listed here.

If you find yourself wanting to read source you don't see referenced
here, that's a sign this digest is stale — update it as part of your
PR.

---

## Project shape (one-liner)

**Tauri 2** desktop app with a **React 19 + Vite + TypeScript**
frontend and a **FastAPI Python sidecar** that owns all DSP. Rust
shell spawns the sidecar at startup, parses a JSON ready-line from
its stdout to learn the port, and loads the React app. Frontend
talks to sidecar over localhost HTTP + SSE. Distributed as a macOS
`.app` inside a `.dmg`.

The DSP engine (`slurmcore.py` + `slurmio.py` at repo root) is
**unchanged from v0.1.6** — only the UI was rewritten. Read
[ADR-0022](docs/adr/0022-tauri-react-migration.md) for the migration
spec.

Current version: **0.2.1** (canonical source: `version` field in
`src-tauri/tauri.conf.json`; mirror in `package.json` and
`src-python/pyproject.toml`).

---

## File map

```
src-tauri/                    ← Tauri 2 Rust shell
    src/main.rs               ← thin entry — calls slurmify_lib::run()
    src/lib.rs                ← all the logic: sidecar lifecycle, discovery, commands
    Cargo.toml                ← Rust deps
    tauri.conf.json           ← canonical version + window/bundle config
    entitlements.plist        ← macOS hardened-runtime entitlements
    capabilities/default.json ← Tauri 2 capability grants for JS side
    binaries/                 ← drop folder for sidecar (populated by build-sidecar.sh)

src/                          ← React 19 + Vite + TypeScript frontend
    main.tsx                  ← React mount point
    App.tsx                   ← root layout
    components/               ← UI components (knobs, sliders, switches, easter eggs…)
    components/ui/            ← shadcn/ui primitives
    hooks/                    ← React hooks (jobs, FX chain, BPM, backend URL)
    stores/                   ← Zustand stores (cross-component state)
    lib/api.ts                ← HTTP/SSE client to the sidecar
    lib/note-mode.ts          ← JS twin of slurmcore._note_to_ms (ADR-0020)
    styles/globals.css        ← Tailwind + custom CSS variables
index.html, vite.config.ts, tailwind.config.ts, package.json

src-python/                   ← FastAPI sidecar
    server.py                 ← entry: port pick, discovery file write, ready-line print
    jobs.py                   ← Job class + JOBS registry + SSE generator
    api/                      ← FastAPI routers
        upload.py             ← POST /upload (audio + video extract)
        slurmify.py           ← POST /slurmify, GET /jobs/{id}/progress, GET /jobs/{id}
        fx.py                 ← POST /burn-fx
        render.py             ← POST /render-video
        analyze.py            ← GET /analyze/{file_id}
        files.py              ← GET /files/{id} (HTTP range), /files/{id}/download
    slurmify-backend.spec     ← PyInstaller spec (onefile; optimize=0 mandatory)
    pyproject.toml            ← sidecar Python deps
    scripts/smoketest.sh      ← quick check: spin up sidecar, hit /health

slurmcore.py                  ← pure DSP (NumPy in/out, no I/O) — unchanged from v0.1.6
slurmio.py                    ← filesystem IO + session-temp dir — unchanged from v0.1.6

scripts/
    build-sidecar.sh          ← PyInstaller → src-tauri/binaries/slurmify-backend-<triple>
    build-dmg.sh              ← clean → sidecar → tauri build → repackage DMG with version

docs/
    TESTER_README.md          ← current Max-facing handoff doc (bundled in DMG)
    UI_DESIGN_BRIEF.md        ← visual design spec for v0.2.0
    UI_DEVELOPMENT_PLAN.md    ← phase-by-phase migration plan (mostly historical now)
    adr/                      ← Architecture Decision Records (0001-0022)

assets/siebaSlurm_A003.mp4    ← pre-encoded loop for video export (ADR-0006)
icon/, src-tauri/icons/       ← Subvoyant cat icon (.icns + source PNGs)
graphic/                      ← AE/PSD sources, NOT bundled (gitignored, ~5 GB of asset packs)

LICENSE                       ← GPL-3.0 + third-party notices (bundled in DMG)
README.md                     ← user-facing setup
TECHNICAL.md                  ← long-form reference (mostly v0.1.x-era — flagged for refresh)
CLAUDE.md                     ← agent operating instructions
AGENT_DIGEST.md               ← THIS FILE
```

### Vestigial v0.1.x files (still in repo, NOT in v0.2.0 runtime)

```
app.py, slurm_ui.py, ui_assets.py     ← old Gradio UI (replaced by src/ + src-python/)
build.sh, slurmify.spec               ← old PyInstaller-of-monolith (replaced by scripts/)
entitlements.plist (root)             ← old root entitlements (replaced by src-tauri/entitlements.plist)
stubs/numba/                          ← old numba shim (sidecar may still need parts of this)
requirements.txt                      ← old top-level deps (replaced by src-python/pyproject.toml)
SLURMER_BETATEST_INSTRUCTIONS.md      ← old release notes (replaced by docs/TESTER_README.md)
```

Don't edit these for v0.2.0+ work. They're kept for reference when
porting v0.1.x features.

---

## Section signposts (grep these)

### Tauri Rust shell — `src-tauri/src/lib.rs`

| Identifier / marker | Role |
|---|---|
| `BackendDiscovery` | struct — must mirror Python's `write_discovery_file` payload (`port`, `pid`, `started_at`) |
| `DISCOVERY_FILENAME` | constant — must match the same name in `src-python/server.py` |
| `read_backend_discovery()` | `#[tauri::command]` — JS calls this on startup to learn the port |
| `reveal_in_finder(path)` | `#[tauri::command]` — bypasses Tauri shell-plugin scope; calls `open -R` directly |
| `quit_app(app)` | `#[tauri::command]` — kills sidecar then `app.exit(0)` (covers RunEvent::Exit non-fire edge case) |
| `kill_sidecar(&app)` | helper — invoked from both `quit_app` and `RunEvent::Exit` for belt-and-braces cleanup |
| `pub fn run()` | entry — registers commands, spawns sidecar via `tauri-plugin-shell`, mounts the WebView |
| `// ── Sidecar lifecycle` | comment marker — sidecar spawn + stdout parsing logic |

### Sidecar (Python/FastAPI) — `src-python/`

| File / identifier | Role |
|---|---|
| `server.py` `write_discovery_file()` | writes `{port, pid, started_at}` JSON to the OS temp dir; format MUST match Rust's `BackendDiscovery` |
| `server.py` `slurmify_ready` print line | Tauri parses stdout for this JSON line; MUST print before `uvicorn.run()` |
| `server.py` CORS allowlist | `tauri://localhost` (prod) + `http://localhost:1420` (dev) — change here AND on the Vite/Tauri config side together |
| `jobs.py` `Job` dataclass | progress tracking; mutated from a background thread by DSP, read by SSE generator |
| `jobs.py` `JOBS` dict | in-memory registry of running jobs by `job_id` |
| `jobs.py` `progress_stream(job_id)` | the SSE generator function |
| `api/upload.py` `POST /upload` | accepts audio or video; routes through ffmpeg if video (preserves v0.1.x universal-upload behaviour, ADR-0009) |
| `api/slurmify.py` `POST /slurmify` | starts a Job thread that calls `slurmcore.slurmify()`; returns `{job_id}` immediately |
| `api/slurmify.py` `GET /jobs/{id}/progress` | SSE stream of `{progress, desc, done, output_id}` |
| `api/fx.py` `POST /burn-fx` | same job pattern, calls `slurmcore.apply_fx()` |
| `api/render.py` `POST /render-video` | same job pattern, calls `slurm_ui.render_video()` legacy helper OR new equivalent (check current import) |
| `api/analyze.py` `GET /analyze/{file_id}` | inline (non-job) call to `detect_slice_points()` for the BPM hint UI |
| `api/files.py` `GET /files/{id}` | HTTP-range-aware streaming (drives WaveformPlayer's seekable playback) |

### React frontend — `src/`

| File / identifier | Role |
|---|---|
| `App.tsx` | root layout; wires up the rack modules, handles backend connection state |
| `lib/api.ts` `getBackendUrl()` | resolves the URL from the Tauri discovery file; cached |
| `lib/api.ts` `api<T>(path, init?)` | typed fetch wrapper — every HTTP call goes through here |
| `lib/api.ts` `invalidateBackendUrl()` | called when health probe fails — forces re-read of discovery file |
| `lib/note-mode.ts` `noteToMs(note, bpm)` | **JS twin of `slurmcore._note_to_ms`** — must produce identical numbers (ADR-0020) |
| `lib/note-mode.ts` `msToClosestNote(ms, bpm)` | reverse direction for the live hint |
| `stores/slurmStore` | source file, slurmify params, output, job state. Persists `params` + `outputFormat` to localStorage. |
| `stores/fxStore` | 8 FX-chain knobs; persists `params` to localStorage. Field names mirror `BurnFxRequest`. |
| `stores/videoStore` | render-video form state |
| `stores/presetStore` | named-preset save/load |
| `stores/skinStore` | skin choice (default / acid / hardware) — persists to localStorage |
| `stores/uiPrefsStore` | misc UI prefs (per-knob unit mode, etc.) |
| `hooks/useBackendUrl` | reads + caches the discovery URL |
| `hooks/useBackend` | health probe + reconnection logic |
| `hooks/useFxChain` | Web Audio chain (dist → ring → delay → phaser); mirrors v0.1.x INIT_JS FX preview |
| `hooks/useSlurmifyJob` | POST /slurmify + SSE consumer |
| `hooks/useBurnFxJob` | POST /burn-fx + SSE consumer |
| `hooks/useRenderVideoJob` | POST /render-video + SSE consumer |
| `hooks/useEffectiveBpm` | resolves override vs auto-detect; matches `detect_slice_points` semantics |
| `hooks/useSkinColors` | reads CSS custom properties for the active skin |
| `components/RackModule` | the gradient-bordered "rack" frame used everywhere |
| `components/WaveformPlayer` | wavesurfer.js wrapper; consumes `/files/{id}` with HTTP range |
| `components/KnobNoteToggle` | knob with ms ⇄ ♪ unit toggle (ADR-0020 in React form) |
| `components/EasterEggHover` | hover-gif system; replaces v0.1.x's `_MAX_GIF_B64` / `_BOB_GIF_B64` / `_HOBERMAN_GIF_B64` |
| `components/Dancer` | processing animation (siena_dancer.gif) |
| `components/VuMeter` | hardware-skin VU meter (Web Audio analyser) |
| `components/SkinPicker` | header skin select |
| `components/UtilityBar` | top utility bar — quit, reveal-temp, randomize-all (Bob/Hoberman-Max gif hosts) |

### DSP — `slurmcore.py` (unchanged from v0.1.6 — ADR-0016)

| Identifier | Role |
|---|---|
| `slurmify(y, sr, ...)` | main pipeline (trim → stretch → slice → per-slice FX → concat → normalize); returns `(ndarray, int)` |
| `detect_slice_points(...)` | returns `(positions, effective_bpm)` — the BPM is canonical for note→ms inside slurmify (single-BPM rule, ADR-0020) |
| `apply_fx(y, sr, ...)` | full FX chain — pure DSP, called by `/burn-fx` |
| `_fx_distortion`, `_fx_ring_mod`, `_fx_delay`, `_fx_phaser` | individual FX nodes |
| `_note_to_ms(note, bpm)` | the **source of truth** for the note grammar (ADR-0020) |
| `_n_samples(y)` | shape-agnostic time-axis length (use everywhere, not `len(y)`) (ADR-0021) |
| `_to_mono(y)` | mono mixdown for librosa beat/onset detection (ADR-0021) |
| `_stereo_pyrb(...)` | wraps pyrubberband with the channels-first ↔ channels-last transpose (ADR-0021) |
| `apply_envelope(...)` | per-slice fade-in/out (anti-click) |
| `DEFAULT_BPM = 120.0` | fallback BPM (mirrored as JS hint fallback in `lib/note-mode.ts`) |

### IO — `slurmio.py` (unchanged from v0.1.6 — ADR-0017)

| Identifier | Role |
|---|---|
| `_asset(rel_path)` | dev vs. bundled-asset path resolver (`sys._MEIPASS`-aware) |
| `_new_temp_path(suffix, prefix)` | **the only sanctioned way to make a temp file** (ADR-0011) |
| `load_audio(path)` | returns `(ndarray, sr)`; handles audio + video via ffmpeg |
| `_write_audio(y, sr, fmt)` | writes ndarray to a session-scoped temp file |
| `SESSION_TMP_DIR` | per-process temp dir (auto-cleaned at exit) |
| `_cleanup_session_tmp()` | atexit handler |
| `_sweep_orphan_session_dirs()` | startup orphan cleanup |
| `_reveal_temp_dir()` | called by the React `reveal-temp` button via `/reveal` (or by Tauri's `reveal_in_finder`) |
| `SUPPORTED_EXTS`, `TARGET_SR`, `_SF_FORMATS`, `_FFMPEG_FORMATS` | format whitelists / constants |

---

## "Where do I add X?" recipes

### A new slurmify parameter

1. Add the field to the slurmify request schema in
   `src-python/api/slurmify.py` (and mirror in the React request type
   in `src/lib/api.ts` or alongside it).
2. Surface a control in `src/App.tsx` (or a sub-component) wired to
   `useSlurmStore`.
3. Pass it into the `slurmcore.slurmify(...)` call inside the job
   function in `api/slurmify.py`.
4. **Implement the DSP step inside `slurmify()` in `slurmcore.py`**.
5. Update `_progress(...)` fractions if the new step is heavy.
6. **If the parameter affects the slurm output and you want it
   preserved in the exported MP4**, add it to the `patch` dict in
   `render_video()` (still in `slurmcore.py` / its caller).

### A new FX

1. **JS preview chain (`src/hooks/useFxChain.ts`)** — create the
   AudioNode, connect into the chain in the right place, expose the
   slider value through `fxStore`.
2. **Python burn parity (`slurmcore.py`)** — implement
   `_fx_<name>(y, sr, ...)` matching the JS graph; add it to
   `apply_fx()` in the same chain order.
3. **Backend request schema** — add the new field to `BurnFxRequest`
   in `src-python/api/fx.py`.
4. **UI** — slider + label in the FX rack module in `src/`.
5. **MP4 metadata** — add to `patch.fx` in the render-video pipeline.

### A new keyboard shortcut

Use the React way: a `useEffect` that adds a `keydown` listener at the
window level, scoped via a ref or focus check. There's no longer a
single `INIT_JS` to land it in.

### A new output format

Add an entry to `_SF_FORMATS` (soundfile-direct) or `_FFMPEG_FORMATS`
(needs the ffmpeg encode branch) in `slurmio.py`. Add it to the
output-format selector in `src/components/` (probably on the
slurm-output rack). No other changes — `_write_audio` dispatches by
name.

### A new skin

1. Add CSS custom properties for the new skin under
   `body[data-skin="<name>"] { ... }` in `src/styles/globals.css`.
2. Add the new option to `SkinPicker.tsx` and `stores/skinStore`.
3. Make sure `useSkinColors` reads any new properties you introduced.

### A new dependency

- **Frontend:** `pnpm add <pkg>`. If it touches Tauri APIs, also
  check `src-tauri/capabilities/default.json`.
- **Sidecar:** `src-python/pyproject.toml` + (if dynamic imports)
  `hiddenimports` in `src-python/slurmify-backend.spec` + (if data
  files) `collect_data_files("name")` in the spec. Then run
  `./scripts/build-sidecar.sh` and smoketest.
- **Rust shell:** `src-tauri/Cargo.toml`. Plugins also need a
  capability grant.

### A new ADR

1. Pick the next number in `docs/adr/`.
2. Copy a recent ADR as a template (e.g., `0022-tauri-react-migration.md`).
3. Add it to the index in `docs/adr/README.md`.
4. Reference it from this digest if it touches a load-bearing
   identifier.

### A new hover-gif easter egg

In v0.2.0 these go through `components/EasterEggHover.tsx` rather than
the v0.1.x base64-inlined CSS approach. Drop the gif under `src/assets/`
or wherever EasterEggHover expects, then mount the component on the
target element with the hover-position config.

### A new place that creates temp files (sidecar)

Use `_new_temp_path(suffix=".ext", prefix="slurm_yourthing_")` from
`slurmio.py`. This is the ONLY way — direct `tempfile.mkstemp()` calls
leak to the system tmpdir and won't be cleaned up at exit. (ADR-0011)

---

## Critical danger zones

Each has an ADR — read it before changing.

### v0.2.0-specific (Tauri / React)

| Zone | ADR | One-line warning |
|---|---|---|
| Sidecar discovery contract | [0022](docs/adr/0022-tauri-react-migration.md) | `BackendDiscovery` struct in lib.rs and `write_discovery_file` in server.py must agree on filename, format, location. Change both in the same commit. |
| `externalBin` is single-file | [0022](docs/adr/0022-tauri-react-migration.md) | PyInstaller must be onefile. Onedir won't bundle through Tauri's externalBin. Cold-start cost (3-5 s) is the price. |
| Ready-line print before uvicorn | [0022](docs/adr/0022-tauri-react-migration.md) | server.py must print the `slurmify_ready` JSON line BEFORE uvicorn.run(). After that, stdout interleaves with request logs. |
| Tauri 2 capabilities | (no ADR yet — file one if scope changes) | Capabilities are deny-by-default. Don't grant broad scopes (`fs:scope-temp-recursive`); keep per-command. |
| Build is signed + notarized | [0025](docs/adr/0025-developer-id-signing-and-notarization.md) | `scripts/build-dmg.sh` resolves `Developer ID Application` from keychain, signs .app + sidecar (re-signed for tauri#11992), notarizes via `xcrun notarytool --keychain-profile slurmify-notary`, staples both .app and DMG. New build host? `xcrun notarytool store-credentials slurmify-notary …` once. `SKIP_NOTARIZE=1` for local-only smoke-test builds. |
| `assets/` must be bundled by the spec | [0024](docs/adr/0024-bundle-project-assets-in-sidecar.md) | PyInstaller doesn't copy project-root `assets/` automatically. The spec walks the folder into `datas` with a build-time guard for `_REQUIRED_ASSETS`. New runtime `_asset()` callers? Add the file to `_REQUIRED_ASSETS`. |

### Carried forward (still apply to the sidecar)

| Zone | ADR | One-line warning |
|---|---|---|
| `optimize=0` in sidecar spec | [0005](docs/adr/0005-pyinstaller-optimize-zero.md) | Must stay 0. Anything else hits "zlib header mismatch" on lazy-loaded modules. |
| Numba | [0002](docs/adr/0002-numba-stub-disable-jit.md) | NUMBA_DISABLE_JIT=1 in the sidecar bootstrap. |
| Video export pipeline | [0006](docs/adr/0006-loop-mp4-stream-copy.md) | The loop is a pre-encoded MP4. `-c:v copy`. Don't reintroduce PNG sequences. |
| MP4 metadata schema | [0008](docs/adr/0008-self-describing-mp4.md) | `description` ends with `PATCH={...JSON...}`. Don't break the schema without a `version` bump. |
| Universal upload routing | [0009](docs/adr/0009-universal-upload-gr-file.md) | Audio passes through; video → ffmpeg extract. Implemented in `api/upload.py`. |
| Temp file cleanup | [0011](docs/adr/0011-session-scoped-temp-cleanup.md) | All sidecar temp files MUST go through `_new_temp_path()`. |
| MAX RANDOM distribution | [0012](docs/adr/0012-max-random-trimodal.md) | Trimodal (stutter/chop/held), NOT log-uniform. Bucket boundaries 5-30 / 100-500 / 1000-4000 ms — gaps are the design. |
| MAX RANDOM auto-shuffle | [0013](docs/adr/0013-auto-shuffle-max-random.md) | Selecting MAX RANDOM auto-checks shuffle. Implement in the React onChange handler, NOT inside `slurmify()`. |
| slurmcore.py purity rule | [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | slurmcore.py must NEVER import os/sys/soundfile/fastapi/shutil/subprocess. Pure DSP only. |
| slurmify() IO refactor | [0016](docs/adr/0016-slurmcore-dsp-extraction.md) | `slurmify()` takes `(y, sr, ...)` and returns `(ndarray, int)`. The api/ layer wraps it with load_audio + _write_audio. |
| slurmio.py purity rule | [0017](docs/adr/0017-slurmio-filesystem-extraction.md) | slurmio.py must NEVER import fastapi/tauri at the top level. |
| Single-BPM rule | [0020](docs/adr/0020-note-mode-time-parameters.md) | The BPM passed to `_note_to_ms` MUST equal the BPM `detect_slice_points` used. detect_slice_points returns `(positions, bpm)` for that reason. |
| Note-mode JS / Python parity | [0020](docs/adr/0020-note-mode-time-parameters.md) | `noteToMs` in `src/lib/note-mode.ts` must produce identical numbers to `_note_to_ms` in slurmcore.py. Change one → change both in the same commit. |
| Channel-layout convention | [0021](docs/adr/0021-stereo-end-to-end.md) | Slurmcore uses (channels, n). soundfile + pyrubberband use (n, channels). Transposes happen at module boundaries. NEVER assume y is 1-D inside slurmcore — use `_n_samples(y)`. |
| Mono mixdown for librosa | [0021](docs/adr/0021-stereo-end-to-end.md) | `librosa.beat.beat_track` and `librosa.onset.onset_detect` need mono. Always pass `_to_mono(y)`. |
| Use `_n_samples`, never `len(y)` | [0021](docs/adr/0021-stereo-end-to-end.md) | `len(y)` returns channel count for 2-D arrays. Use `_n_samples(y)` (`y.shape[-1]`). |

### Historical (v0.1.x only)

[ADR-0014](docs/adr/0014-gradio-quirks-collected.md) catalogs Gradio
5+/6.x oddities. Read it only if maintaining the v0.1.x branch or
porting an old behaviour. ADR-0003 (createMediaElementSource one-shot)
is also v0.1.x-only — the React `useFxChain` is built fresh and
doesn't have the same constraint.

---

## Quick-run reference

```bash
# Dev: sidecar in one terminal, Tauri in another
python src-python/server.py
pnpm tauri dev

# Frontend-only against an already-running sidecar (component work)
pnpm dev   # → http://localhost:1420

# Type-check
pnpm tsc -b --noEmit
python3 -c "import ast; ast.parse(open('slurmcore.py').read()); print('slurmcore OK')"
python3 -c "import ast; ast.parse(open('slurmio.py').read()); print('slurmio OK')"

# Sidecar smoke test
src-python/scripts/smoketest.sh

# Sidecar build only
./scripts/build-sidecar.sh

# Full release DMG (3-5 min)
./scripts/build-dmg.sh
# Reuse the existing sidecar bundle
SKIP_SIDECAR=1 ./scripts/build-dmg.sh

# Regenerate the loop MP4 from source PNGs (ADR-0006)
ffmpeg -framerate 24 -i graphic/siebaSlurm_A003/siebaSlurm_A003_%05d.png \
       -vf "scale=1280:720:flags=lanczos,format=yuv420p" \
       -c:v libx264 -preset slow -crf 30 -movflags +faststart -an \
       assets/siebaSlurm_A003.mp4
```

---

## Version-bump checklist

When asked to bump to `X.Y.Z`, edit ALL of:

1. `src-tauri/tauri.conf.json` — `version` (canonical source).
2. `package.json` — `version` (must match).
3. `src-python/pyproject.toml` — `version` (must match).
4. `docs/TESTER_README.md` — title, footer, new "What's new in
   X.Y.Z" section at the top.
5. `AGENT_DIGEST.md` — last-updated stamp at the bottom + the
   "Current version" reference near the top of this file.
6. `TECHNICAL.md` — last-updated stamp at the bottom.
7. `SLURMCORE_COMPARISON.md` — version stamp in the footer (DSP
   content remains accurate).

The DMG and `.app` filenames are auto-derived from the
`tauri.conf.json` version by `scripts/build-dmg.sh`. Don't update
them separately. Verify no `X.Y.(Z-1)` references remain via:

```bash
grep -rn 'X\.Y\.(Z-1)' --include='*.json' --include='*.toml' \
    --include='*.ts' --include='*.tsx' --include='*.py' --include='*.md' . \
    | grep -v '/node_modules/' | grep -v '/target/' \
    | grep -v '/.venv/' | grep -v '/build/' | grep -v '/dist/'
```

---

## Maintenance — when this digest is wrong

If you read this digest, then look at the code, and find that the
identifiers don't match or the file map is wrong:

1. **Don't trust the digest.** Re-derive what you need.
2. **Update the digest** as part of the same change.
3. **If the change is significant**, add an ADR.

The digest going stale is itself a signal — it means the codebase
has drifted from a state that was previously well-mapped.

---

*Last updated: 2026-05-09 · v0.2.1 · Tauri 2 + React 19 + FastAPI sidecar (ADR-0022)*
