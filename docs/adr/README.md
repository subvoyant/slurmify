# Architecture Decision Records

This folder records the *why* behind non-obvious choices in the Slurmify
codebase. Each ADR is short, self-contained, and dated. The format is
[MADR](https://adr.github.io/madr/) — Markdown ADR — with sections for
**Context**, **Decision**, and **Consequences**.

## When to add an ADR

Write a new ADR when you:

- Make a choice that wasn't obvious and that future-you (or a future
  agent) might want to revisit.
- Adopt a workaround for a third-party bug or platform constraint.
- Pick one viable design over another and want to record the trade-offs.

Don't write an ADR for the obvious or the easily-revisited.

## When to read these

Whenever you're about to change something the digest
(`/AGENT_DIGEST.md`) flags as load-bearing. Almost every entry in this
folder corresponds to an item in the digest's "danger zones" list.

## Index

| #    | Title                                                                       | Status   |
|------|-----------------------------------------------------------------------------|----------|
| [0001](0001-single-file-app.md)              | Single-file `app.py` design                                | Accepted |
| [0002](0002-numba-stub-disable-jit.md)        | Numba stub + `NUMBA_DISABLE_JIT=1` instead of bundling LLVM | Accepted |
| [0003](0003-createmediaelementsource-once.md) | FX chain binds to a dedicated `<audio>` element exactly once | Accepted |
| [0004](0004-init-js-via-head.md)              | Inject INIT_JS via `launch(head=...)`, not `gr.Blocks(js=)`  | Accepted |
| [0005](0005-pyinstaller-optimize-zero.md)     | PyInstaller `optimize=0` is mandatory                       | Accepted |
| [0006](0006-loop-mp4-stream-copy.md)          | Pre-encoded loop MP4 + stream-copy for video export         | Accepted |
| [0007](0007-skin-system-data-skin.md)         | Pluggable skins via `body[data-skin]`                       | Accepted |
| [0008](0008-self-describing-mp4.md)           | Embed slurm patch as JSON in the MP4 `description` atom     | Accepted |
| [0009](0009-universal-upload-gr-file.md)      | Universal upload via `gr.File`, not `gr.Audio` for input    | Accepted |
| [0010](0010-favicon-via-js-injection.md)      | Favicon via JS injection (head/`favicon_path` both unreliable) | Accepted |
| [0011](0011-session-scoped-temp-cleanup.md)   | Session-scoped temp directory + atexit + orphan sweep       | Accepted |
| [0012](0012-max-random-trimodal.md)           | MAX RANDOM uses trimodal distribution, not log-uniform      | Accepted |
| [0013](0013-auto-shuffle-max-random.md)       | Selecting MAX RANDOM auto-checks the shuffle box            | Accepted |
| [0014](0014-gradio-quirks-collected.md)       | Collected Gradio behavior quirks (living catalog)           | Accepted |
| [0015](0015-modular-file-structure.md)        | Modular file structure — extract `ui_assets.py` (Phase 1)  | Accepted |
| [0016](0016-slurmcore-dsp-extraction.md)      | Extract pure DSP into `slurmcore.py` (Phase 2)              | Accepted |
| [0017](0017-slurmio-filesystem-extraction.md) | Extract filesystem IO into `slurmio.py` (Phase 3)           | Accepted |
| [0018](0018-slurm-ui-extraction.md)           | Extract Gradio UI orchestration into `slurm_ui.py` (Phase 4) | Accepted |
| [0019](0019-bar-mask-beat-dropout.md)         | Beat mask — per-beat dropout within each bar (chip strip UI) | Accepted |
| [0020](0020-note-mode-time-parameters.md)     | Note-mode time parameters — per-slider ms ⇄ ♪ toggle         | Accepted |
| [0021](0021-stereo-end-to-end.md)             | Stereo end-to-end through the slurmify pipeline              | Accepted |
| [0022](0022-tauri-react-migration.md)         | Tauri 2 + React 19 + FastAPI sidecar migration (v0.2.0)      | Accepted |
| [0023](0023-bundle-cli-binaries-in-sidecar.md) | Bundle ffmpeg + rubberband CLIs at `_MEIPASS` root           | Accepted |
| [0024](0024-bundle-project-assets-in-sidecar.md) | Bundle project `assets/` in the sidecar via spec `datas`   | Accepted |
| [0025](0025-developer-id-signing-and-notarization.md) | Developer ID signing + notarization in `build-dmg.sh`  | Accepted |

## Numbering

Sequential, four-digit, zero-padded. Never reuse a number; if an ADR is
withdrawn, mark it **Superseded** and link to the replacement.
