# CLAUDE.md — Slurmify orientation for AI agents

> **🛑 READ `AGENT_DIGEST.md` BEFORE DOING ANYTHING ELSE.**
>
> The digest is a precomputed code map: section signposts, load-bearing
> identifiers, "where do I add X" recipes, and links to the ADRs that
> explain non-obvious decisions. Reading it first saves you a full
> pass over `app.py` (~2 100 lines) and tells you which corners of the
> code have ADR-protected invariants.
>
> When you change anything that the digest flags as load-bearing,
> consult the matching ADR in `docs/adr/` before editing. If you
> introduce a new non-obvious decision, **write a new ADR** as part of
> the same change.

This file is the operational top sheet: what's where, conventions to
respect, and the small set of mistakes that have a high blast radius
in this codebase. `TECHNICAL.md` has the comprehensive narrative
reference for humans; **read `TECHNICAL.md` for anything that requires
deeper understanding than the digest provides**.

---

## What this project is

Slurmify is a single-file Python application (`app.py`, ~3000 lines)
that runs a local Gradio UI for chopping, time-stretching, and
applying effects to audio (and now video) files. Distribution is a
code-signed, notarized macOS `.app` bundle inside a `.dmg`, built via
`build.sh` and `slurmify.spec`.

Current version: see the `<div class="slurm-tag">` in `app.py` (truth
copy is `build.sh`'s `VERSION`).

---

## File map

| Path | What it is |
|---|---|
| `app.py` | Everything — bootstrap, audio engine, FX DSP, INIT_JS string, CSS string, Gradio UI, `__main__`. Single-file by design. |
| `requirements.txt` | Python dependencies. Pinned with `>=` only. |
| `slurmify.spec` | PyInstaller spec. `optimize=0` is mandatory; do not change. |
| `build.sh` | Code-sign + notarize + DMG pipeline. |
| `entitlements.plist` | macOS hardened-runtime entitlements. |
| `stubs/numba/__init__.py` | Pass-through stub so librosa imports work without real numba/llvmlite in the bundle. |
| `assets/siena_dancer.gif` | Loading animation shown during slurmify processing. |
| `assets/siebaSlurm_A003.mp4` | Pre-encoded 1.5 s 1920×1080 H.264 loop animation used by `render_video()`. Stream-copied (no re-encode) into the YouTube MP4 export so render time is dominated by the AAC audio encode — about 100× faster than re-decoding a PNG sequence. Source frames live in `graphic/siebaSlurm_A003/`; regenerate via the ffmpeg one-liner in the comment at the top of `render_video()` in app.py. |
| `assets/subvoyant_bug.png` | Legacy bug overlay PNG (no longer used by `render_video()` — branding is baked into the A003 loop). Kept on disk in case a future skin or feature wants a corner watermark. |
| `icon/` | `.icns` + source PNGs. Siena cat icon lives base64'd inline in `app.py` (`_ICON_B64`); same image is used for the browser favicon (ADR-0010). |
| `graphic/max.gif` | Max-the-tester face. Hover gif on MAX RANDOM radio option. Base64-inlined as `_MAX_GIF_B64`. |
| `graphic/hobermanmax.gif` | Hoberman-Max. Hover gif on 🎲 randomize all button (bottom-up spring). Base64-inlined as `_HOBERMAN_GIF_B64`. |
| `graphic/RGBOB.gif` | Bob. Hover gif on 📁 reveal temp files button (bottom-up spring). Base64-inlined as `_BOB_GIF_B64`. |
| `LICENSE` | GPL-3.0 + third-party notices. Bundled into the DMG by `build.sh`. |
| `README.md` | User-facing setup. |
| `TECHNICAL.md` | Comprehensive engineering reference. Narrative; humans-and-agents-friendly. |
| `AGENT_DIGEST.md` | **Precomputed code map for agents — read first.** Section signposts, identifiers, recipes. |
| `SLURMCORE_COMPARISON.md` | Long-form: how Slurmify's method differs from general slurmcore practice (newcomer + expert sections). Bundled into the DMG by `build.sh`. |
| `docs/adr/` | Architecture Decision Records (0001–0014). Index in `docs/adr/README.md`. |
| `CLAUDE.md` | This file. |
| `SLURMER_BETATEST_INSTRUCTIONS.md` | Release notes for testers. Update on every version bump. Bundled into the DMG. |

---

## How to run / test / build

```bash
# Dev run
source .venv/bin/activate
python app.py
# → http://127.0.0.1:7860

# Syntax check after edits
python3 -c "import ast; ast.parse(open('app.py').read())"

# Full build (signed + notarized + DMG; takes 3–8 min)
./build.sh
```

There are currently **no automated tests**. Verification is manual
(load a file, slurmify, play, twist FX, burn). When making non-trivial
changes, exercise both the Python audio path and the Web Audio FX
preview before declaring done.

---

## Conventions

### Code style

- **Single file by design.** Do not split `app.py` into modules
  without a strong reason — PyInstaller analysis is simpler with one
  entry point.
- **Use `_asset(rel_path)`**, not `__file__`-based paths, for any
  bundled asset. It's the only thing that works in both dev and
  bundled modes.
- **Use `gr.Error(msg)`** for user-facing failures. Anything else
  surfaces as an ugly red error box.
- **Comment block headers** use the `# ── name ───` Unicode-line style
  consistent with the rest of the file.

### Python ↔ JavaScript boundary

Three patterns and only three:

1. **Python work + JS reaction (chained):** `btn.click(fn=py_fn,
   ...).then(fn=None, js="(d)=>{...}", ...)`. Use this when JS needs
   to react after Python finishes.
2. **JS-only (no Python round-trip):** `btn.click(fn=None,
   inputs=[...], outputs=[...], js="(...)=>[...]")`. Used for slider
   → Web Audio mirroring, in/out time probes, clear button.
3. **Pure Python:** `btn.click(fn=py_fn, ...)` with no JS.

The JS string in `js=...` MUST be a single function expression
(`"(...)=>{...}"` or `"function(...){...}"`). Bare statements or
self-invoking IIFEs will silently break the page on Gradio 6.

### Where INIT_JS goes

The big browser-side script lives in the `INIT_JS` Python multiline
string at the top of the UI section of `app.py`. It is injected via
`ui.launch(head=f"<script>\n{INIT_JS}\n</script>")` — **not** via
`gr.Blocks(js=...)` and **not** via `<script>` inside `gr.HTML`. Both
of those alternatives are unreliable on Gradio 6.

### Adding dependencies

Adding a Python dep is *three* edits, not one:

1. `requirements.txt` — `>=` constraint.
2. `slurmify.spec` — add to `hiddenimports` if it has dynamic imports
   (most things do).
3. `slurmify.spec` — `collect_data_files("name")` if it ships data.

Then run `./build.sh` and launch the resulting `.app` to confirm
nothing broke.

---

## Danger zones — read before touching

These are bugs that have either bitten us or are guaranteed to bite if
ignored. The full table with one-line warnings + ADR links lives in
`AGENT_DIGEST.md`; the top items, with extra context:

1. **`createMediaElementSource` is one-shot per `<audio>` element.**
   The FX chain binds to a dedicated `<audio id="slurm-fx-audio">` we
   own, exactly once. Never rebind to the same element. Never bind to
   Gradio's WaveSurfer-managed element. (ADR-0003)
2. **AudioContext starts suspended.** It must be resumed during a real
   user gesture. We resume from a `play` event listener attached to
   the preview element. Do not move the resume call into a
   `setInterval` or onload handler.
3. **Bundle path is `Contents/Frameworks/`** on macOS PyInstaller 6
   (not `MacOS/`). `sys._MEIPASS` resolves there. The bootstrap and
   `build.sh`'s `RB_BIN` path both depend on this.
4. **`optimize=0` in `slurmify.spec` is mandatory.** PyInstaller's
   bytecode optimisation breaks lazy-loaded modules with a "zlib
   header mismatch". Do not change. (ADR-0005)
5. **`hiddenimports` is intentionally long.** Don't trim
   speculatively. Add to it; remove only with a clean-machine smoke
   test.
6. **WaveSurfer's `<audio>` is in a shadow root.** Plain
   `querySelectorAll('audio')` misses it. Use `_fxWalk(root)` from
   INIT_JS, which recurses into `el.shadowRoot`. (ADR-0003)
7. **Universal upload routing — `gr.Audio` rejects video MIME types
   server-side** regardless of what the browser file picker accepts.
   The single visible drop zone is `gr.File(file_types=None)`; an
   audio file passes through directly to `audio_in`, anything else
   gets ffmpeg-extracted first. Don't try to make `gr.Audio` accept
   video — it can't. (ADR-0009)
8. **All temp files MUST go through `_new_temp_path()`.** Direct
   `tempfile.mkstemp()` calls leak to the system tmpdir forever and
   bypass the session cleanup. (ADR-0011)
9. **Favicon is set via JS injection, not `head=` or `favicon_path`.**
   Both of those get overridden by Gradio at runtime. JS injection
   with a setTimeout retry chain is the only thing that wins. (ADR-0010)
10. **MAX RANDOM uses a TRIMODAL distribution, not log-uniform.**
    The bucket gaps (no 30-100ms or 500-1000ms slices) are the design,
    not an oversight. Filling them in destroys the audible chaos.
    (ADR-0012)
11. **Selecting MAX RANDOM auto-checks the shuffle box** via a
    `resolution.change()` handler. Do NOT internalize this in
    `slurmify()` — keep the UI state visible and overridable. (ADR-0013)
12. **Single-BPM rule for note-mode time params.** The four musical
    sliders (stutter skip, beat trim start/end, beat gap) can each be
    toggled into "♪" mode. The note→ms conversion inside `slurmify()`
    MUST use the BPM returned by `detect_slice_points` — that's why
    that function now returns `(positions, bpm)`. Don't recompute BPM
    elsewhere; don't decouple the slicer's tempo from the gap/trim
    tempo. (ADR-0020)
13. **Note-mode JS twin must match Python.** `_slurmNoteToMs` in
    INIT_JS must produce the same numbers as `_note_to_ms` in
    slurmcore.py. The JS exists for the live "≈ NN ms @ BPM" hint;
    Python is the source of truth for the slurm output. Change the
    grammar in one place → change it in the other in the same commit.
    (ADR-0020)
14. **Channel-layout boundary rule.** Slurmcore uses
    `(n_channels, n_samples)` (channels-first) for stereo. soundfile
    and pyrubberband both use `(n_samples, n_channels)`
    (channels-last). Transposes happen at the boundaries — `.T`
    before `_write_audio`, `_stereo_pyrb` around pyrb calls. NEVER
    assume `y` is 1-D inside slurmcore — use `_n_samples(y)` for
    the time-axis length and `y[..., a:b]` for time-axis slicing.
    (ADR-0021)
15. **Pass mono mixdowns to librosa beat/onset detection.**
    `librosa.beat.beat_track` and `librosa.onset.onset_detect`
    interpret 2-D input differently than our convention. Always
    feed them `_to_mono(y)`; the returned sample positions apply
    correctly to the original stereo array. (ADR-0021)

**For Gradio-specific oddities** (label rendering changes when `info=`
is added, `:focus-within` block highlight, `gr.Audio.interactive=False`
also kills transport, etc.) → read [ADR-0014](docs/adr/0014-gradio-quirks-collected.md)
first. It's a living catalog of "don't waste time on this again"
gotchas we've already paid for.

**For Apple build-time flakiness** — `codesign --timestamp` calls
`timestamp.apple.com`. That service goes down occasionally (a few
times a year). When you see "The timestamp service is not available"
in build output, it's not a code bug — wait 5-10 minutes and rerun
`./build.sh`. Don't remove `--timestamp`, that breaks notarization.

---

## Version-bump checklist

When the user asks to bump to version X.Y.Z, edit ALL of:

1. `build.sh` — `VERSION="X.Y.Z"`
2. `slurmify.spec` — both `CFBundleShortVersionString` and
   `CFBundleVersion`
3. `app.py` — the `<div class="slurm-tag">` in the header HTML
4. `app.py` — the `__version__ = "..."` constant near `render_video`
5. `SLURMER_BETATEST_INSTRUCTIONS.md` — title, install-step DMG
   filename, and footer
6. `SLURMER_BETATEST_INSTRUCTIONS.md` — add a new "What's new in
   X.Y.Z" section at the top with a brief summary of changes
7. `AGENT_DIGEST.md` — last-updated stamp at the bottom + the
   "Current version" reference near the top
8. `TECHNICAL.md` — last-updated stamp at the bottom
9. `SLURMCORE_COMPARISON.md` — version stamp in the footer
10. `docs/adr/0008-self-describing-mp4.md` — example version field
    in the JSON sample (illustrative; safe to update for consistency)

Then verify no `X.Y.(Z-1)` references remain via:
```bash
grep -rn 'X\.Y\.(Z-1)' --include='*.py' --include='*.sh' \
    --include='*.spec' --include='*.md' . \
    | grep -v '/.venv/' | grep -v '/build/' | grep -v '/dist/'
```
The only remaining matches should be historical entries in
`SLURMER_BETATEST_INSTRUCTIONS.md` (the previous "What's new" section
and any references like "released in X.Y.(Z-1)") — those are
intentional history, not stale references.

The DMG filename is auto-derived from `VERSION` in `build.sh`; don't
update it separately.

---

## When asked to debug FX preview issues

Read `TECHNICAL.md` §11 ("Debugging recipes") first. Then ask the user
to open browser DevTools and report what `[slurm]` / `[SLURM]` console
lines appear. The diagnostic tree there matches the actual code paths
in `INIT_JS` and the `audio_out.change` handler.

Common causes, in rough order of likelihood:
1. INIT_JS not running → check `ui.launch(head=...)` is intact.
2. `#slurm-fx-audio` not in the DOM → check the `gr.HTML` block in
   the FX accordion still exists.
3. Gradio's audio element src isn't being found by `_fxWalk` → check
   if the underlying selector logic still matches the current Gradio
   release.
4. Chain bound but no sound → AudioContext stuck in `suspended`.
   Verify the `play` event listener is attached.

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

- Comprehensive technical reference: `TECHNICAL.md`
- Architecture decisions: `docs/adr/README.md`
- Code map for agents: `AGENT_DIGEST.md`
- User docs: `README.md`, `SLURMER_BETATEST_INSTRUCTIONS.md`
