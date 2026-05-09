# ADR-0022: Tauri + React migration plan

- **Status:** Proposed
- **Date:** 2026-05
- **Version:** 0.2.0 (target)
- **Supersedes:** UI_DEVELOPMENT_PLAN.md §4–§5 (those sections become historical
  once this ADR is accepted; the Phase 5/6 Gradio polish work is dropped in
  favour of a clean cut to the new architecture)

## 1. Context

By v0.1.6, every Phase 4 modularisation goal has been met: `slurmcore.py`
and `slurmio.py` are completely UI-agnostic, `slurm_ui.py` is a thin
Gradio adapter, and the Web Audio FX chain in `INIT_JS` already runs
fully in the browser. The DSP engine is no longer the bottleneck; the
UI layer is.

The user's verdict after shipping stereo end-to-end was "Gradio is a
dead end" — every creative feature we add inside Gradio (XY pads, A/B
players, slice-grid editors) gets rewritten in the eventual migration,
and the `!important` CSS war + INIT_JS string-injection workarounds
keep accumulating. The marginal cost of each new feature on Gradio is
rising; the marginal cost on a real frontend is falling because the
DSP engine is already perfectly portable.

The decision in this ADR is to skip Phase 6 entirely and migrate
straight to Tauri + React. UI_DEVELOPMENT_PLAN.md anticipated this
("if Gradio friction is still significant, Phase 7 should be the
Tauri migration"); the friction is significant.

## 2. The big-picture decision

Replace Gradio with a Tauri 2 desktop wrapper hosting a React + Vite +
TypeScript frontend that talks to a FastAPI Python backend running as
a Tauri sidecar process over localhost HTTP + SSE.

```
┌────────────────────────────────────────────────────────────┐
│  Tauri 2 macOS .app                                        │
│  ┌──────────────────────────┐  ┌──────────────────────┐   │
│  │  WebView (React + Vite)  │  │  Rust (Tauri shell)  │   │
│  │  - Zustand store         │  │  - spawns sidecar    │   │
│  │  - WaveSurfer 7          │  │  - reads port from   │   │
│  │  - useFxChain hook       │  │    sidecar stdout    │   │
│  │  - shadcn/ui + Tailwind  │  │  - native menus      │   │
│  └────────────┬─────────────┘  └──────────┬───────────┘   │
│               │                            │               │
│               │  HTTP/SSE on localhost     │  spawn()      │
│               │  (port from stdout)        │               │
│               ▼                            ▼               │
│  ┌────────────────────────────────────────────────────┐   │
│  │  PyInstaller-bundled Python sidecar               │   │
│  │  - FastAPI + uvicorn                               │   │
│  │  - sse-starlette for progress                      │   │
│  │  - slurmcore.py        (verbatim from v0.1.6)      │   │
│  │  - slurmio.py          (verbatim from v0.1.6)      │   │
│  │  - librosa, pyrubberband, soundfile, ffmpeg        │   │
│  └────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

Slurmcore and slurmio cross the boundary unchanged. Everything that
was Gradio (`slurm_ui.py`, `ui_assets.py`'s INIT_JS and CUSTOM_CSS,
`build_ui()`) is replaced by the React frontend.

## 3. Library decisions (versions verified against npm registry / PyPI)

### Frontend

| Package                       | Version pinned | Role                                          |
|-------------------------------|---------------|-----------------------------------------------|
| `react`                       | `^19.0.0`     | UI framework. Locked at 19 (decision 2026-05-08); wavesurfer-react 1.0.12 supports it. |
| `react-dom`                   | `^19.0.0`     | DOM renderer. |
| `typescript`                  | `^5.5`        | Static typing. Pays off heavily for audio types and DSP params. |
| `vite`                        | `^5.4`        | Build tool. Fast HMR; plays well with Tauri dev server. |
| `@vitejs/plugin-react-swc`    | `^3.7`        | React Fast Refresh via SWC. |
| `tailwindcss`                 | `^3.4`        | Utility CSS. Skin variants via `[data-skin]` attribute. (v4 is current but v3 is the stable default for shadcn/ui at time of writing — re-evaluate at install.) |
| `shadcn/ui`                   | (CLI-installed) | Component primitives. Slider, Dialog, Toggle, Tabs, Accordion, Popover. Radix-based, accessible. |
| `lucide-react`                | `^0.453`      | Icon set. Used by shadcn. |
| `zustand`                     | `^5.0.13`     | State management. Smaller than Redux, simpler than Recoil, perfect for our scale. |
| `wavesurfer.js`               | `^7.12.6`     | Waveform rendering + audio playback. Peer-dep of `@wavesurfer/react`. |
| `@wavesurfer/react`           | `^1.0.12`     | Official React hook (`useWavesurfer`). Exposes the underlying audio element so we can bind the FX chain (ADR-0003 still applies). |
| `@tauri-apps/api`             | `^2.11.0`     | Tauri 2 frontend SDK. |
| `@tauri-apps/plugin-shell`    | `^2`          | Sidecar spawning + child process IPC from Rust. |

### Backend

| Package         | Version pinned | Role                                                     |
|-----------------|---------------|----------------------------------------------------------|
| `fastapi`       | `>=0.115`     | HTTP server. Same ASGI engine Gradio uses internally — proven on this stack. |
| `uvicorn`       | `>=0.32`      | ASGI runner. Stdlib of the FastAPI world. |
| `sse-starlette` | `>=2.1`       | Server-Sent Events for progress streaming. Simpler than WebSocket; one-way is all we need. |
| `python-multipart` | `>=0.0.12` | File upload form handling. FastAPI requires it for `UploadFile`. |
| `librosa`, `pyrubberband`, `soundfile`, `numpy`, `scipy` | (existing) | DSP dependencies — unchanged. |

### Build & distribution

| Tool              | Role                                              |
|-------------------|---------------------------------------------------|
| `tauri-cli` v2    | Bundle macOS `.app` + DMG, handle code signing.   |
| `pyinstaller` 6   | Bundle the Python backend into a single binary.   |
| `cargo` (Rust)    | Build the Tauri shell. Comes with rustup.         |
| `pnpm` | Frontend package manager. Locked (decision 2026-05-08). Faster than npm, stricter than yarn classic. |

## 4. Backend design

### 4.1 File structure

```
slurmify/
├── src-python/                    ← NEW: FastAPI backend
│   ├── server.py                  ← uvicorn entrypoint, prints port to stdout
│   ├── api/
│   │   ├── __init__.py
│   │   ├── upload.py              ← /upload endpoint
│   │   ├── slurmify.py            ← /slurmify, /jobs/{id}/progress
│   │   ├── fx.py                  ← /burn-fx
│   │   ├── render.py              ← /render-video
│   │   └── files.py               ← /files/{id} — range request serving
│   ├── jobs.py                    ← in-memory job tracker (uuid → status + progress)
│   └── pyproject.toml
├── slurmcore.py                   ← UNCHANGED from v0.1.6
├── slurmio.py                     ← UNCHANGED from v0.1.6 (mostly — see §10)
├── src-tauri/                     ← NEW: Tauri Rust shell
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── build.rs
│   ├── icons/                     ← copied from existing icon/
│   ├── entitlements.plist         ← copied + extended from existing
│   └── src/
│       └── main.rs                ← spawns sidecar, reads port, serves window
├── src/                           ← NEW: React frontend
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   ├── hooks/
│   ├── stores/
│   └── styles/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── components.json                ← shadcn/ui config
└── (legacy v0.1.6 files retained on a `gradio-archive` branch for reference)
```

### 4.2 Endpoint surface

| Method | Path                       | Purpose                                                | Notes |
|--------|----------------------------|--------------------------------------------------------|-------|
| `POST` | `/upload`                  | Accept any audio/video file, return `file_id` + meta   | Reuses `_route_upload` ffmpeg extraction logic from v0.1.6 |
| `POST` | `/slurmify`                | Run slurmify; return `job_id` immediately              | Background task; client subscribes to progress via SSE |
| `GET`  | `/jobs/{job_id}/progress`  | SSE stream of `{progress, desc, done, output_id?}`     | Closes when `done: true` |
| `GET`  | `/jobs/{job_id}`           | Polling fallback for progress (in case SSE is flaky)   | Same payload, single response |
| `POST` | `/burn-fx`                 | Apply FX chain to an existing audio file               | Same job pattern as `/slurmify` |
| `POST` | `/render-video`            | YouTube MP4 export                                     | Same job pattern; long-running |
| `GET`  | `/files/{id}`              | Serve audio/video output. Supports HTTP range requests | Required for WaveSurfer seek-to-position on large files |
| `GET`  | `/files/{id}/download`     | Same content, `Content-Disposition: attachment` header | For "save as…" UX |
| `GET`  | `/health`                  | Simple liveness probe                                  | Tauri shell uses this to detect when sidecar is ready |

### 4.3 server.py — port-on-stdout pattern

```python
# src-python/server.py
import socket, sys, json
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import upload, slurmify, fx, render, files

app = FastAPI(title="Slurmify Backend", version="0.2.0")

# CORS: Tauri webview origin is `tauri://localhost` on macOS.
# Allow that + http://localhost:* for dev mode (Vite serves on 1420 by default).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(slurmify.router)
app.include_router(fx.router)
app.include_router(render.router)
app.include_router(files.router)

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}

def find_free_port() -> int:
    """Bind to port 0 to let the OS pick an unused port, then release it
    just long enough that uvicorn can rebind. Tiny race window in theory;
    in practice macOS doesn't reuse a port we just released within the
    millisecond uvicorn takes to grab it. If it ever bites, retry with a
    new port from the same call."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

if __name__ == "__main__":
    port = find_free_port()
    # CRITICAL: print the port BEFORE uvicorn starts so the Tauri shell can
    # parse it from stdout. Use a stable JSON line prefix so the parsing
    # is deterministic even if uvicorn dumps its own logs first.
    print(json.dumps({"slurmify_ready": True, "port": port}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

### 4.4 slurmify.py — background job + SSE progress

```python
# src-python/api/slurmify.py
import asyncio, uuid
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from slurmcore import slurmify
from slurmio import load_audio, _write_audio
from jobs import JOBS, Job

router = APIRouter()

class SlurmifyRequest(BaseModel):
    file_id:               str
    speed:                 float = 2.0
    resolution:            str   = "1/16"
    transient_sensitivity: float = 0.5
    envelope_ms:           float = 2.0
    preserve_pitch:        bool  = True
    pitch_shift_semitones: float = 0
    randomize_order:       bool  = False
    reverse_chance:        float = 0
    stutter_chance:        float = 0
    stutter_skip_ms:       float = 0
    stutter_max_reps:      int   = 0
    stutter_spread:        float = 0
    beat_trim_start_ms:    float = 0
    beat_trim_end_ms:      float = 0
    beat_gap_ms:           float = 0
    bpm_override:          float | None = None
    start_sec:             float = 0
    end_sec:               float = 0
    seed:                  int | None = None
    beat_mask:             list[bool] | None = None
    output_format:         str = "wav"
    # note-mode (ADR-0020) — empty string means "use ms"
    stutter_skip_note:     str = ""
    beat_trim_start_note:  str = ""
    beat_trim_end_note:    str = ""
    beat_gap_note:         str = ""

@router.post("/slurmify")
async def start_slurmify(req: SlurmifyRequest, bg: BackgroundTasks):
    job = Job(id=str(uuid.uuid4()))
    JOBS[job.id] = job
    bg.add_task(_run_slurmify, job, req)
    return {"job_id": job.id}

async def _run_slurmify(job: Job, req: SlurmifyRequest):
    """Run slurmify in a thread (slurmify is blocking CPU-bound DSP).
    Use a custom progress callback that mutates the Job so the SSE
    endpoint can stream updates."""
    def _progress(frac: float, desc: str = ""):
        job.progress = frac
        job.desc = desc

    try:
        # Resolve the upload path from the file_id (uploads.py stores them).
        from api.upload import resolve_path
        src_path = resolve_path(req.file_id)
        y, sr = load_audio(src_path)   # stereo-aware (ADR-0021)

        y_out, sr_out = await asyncio.to_thread(
            slurmify,
            y=y, sr=sr,
            speed=req.speed, resolution=req.resolution,
            transient_sensitivity=req.transient_sensitivity,
            envelope_ms=req.envelope_ms, preserve_pitch=req.preserve_pitch,
            pitch_shift_semitones=req.pitch_shift_semitones,
            randomize_order=req.randomize_order,
            reverse_chance=req.reverse_chance,
            stutter_chance=req.stutter_chance,
            stutter_skip_ms=req.stutter_skip_ms,
            stutter_max_reps=req.stutter_max_reps,
            stutter_spread=req.stutter_spread,
            beat_trim_start_ms=req.beat_trim_start_ms,
            beat_trim_end_ms=req.beat_trim_end_ms,
            beat_gap_ms=req.beat_gap_ms,
            bpm_override=req.bpm_override,
            start_sec=req.start_sec, end_sec=req.end_sec,
            seed=req.seed, beat_mask=req.beat_mask,
            stutter_skip_note=req.stutter_skip_note,
            beat_trim_start_note=req.beat_trim_start_note,
            beat_trim_end_note=req.beat_trim_end_note,
            beat_gap_note=req.beat_gap_note,
            _progress=_progress,
        )

        # Channel-layout boundary (ADR-0021): transpose stereo for soundfile.
        if y_out.ndim == 2:
            y_out = y_out.T
        out_path = _write_audio(y_out, sr_out, req.output_format)
        from api.files import register_output
        job.output_id = register_output(out_path)
        job.done = True
    except Exception as e:
        job.error = str(e)
        job.done = True

@router.get("/jobs/{job_id}/progress")
async def progress_stream(job_id: str):
    """SSE: stream {progress, desc, done, output_id, error} until done."""
    job = JOBS.get(job_id)
    if not job:
        return {"error": "unknown job"}

    async def gen():
        last = (-1.0, "")
        while True:
            cur = (job.progress, job.desc)
            if cur != last or job.done:
                yield {
                    "data": Job.dump_json(job)
                }
                last = cur
            if job.done:
                break
            await asyncio.sleep(0.1)
    return EventSourceResponse(gen())
```

### 4.5 files.py — HTTP range requests for WaveSurfer

```python
# src-python/api/files.py
import os
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

router = APIRouter()
_OUTPUTS: dict[str, str] = {}   # file_id → absolute path

def register_output(path: str) -> str:
    file_id = os.path.basename(path)
    _OUTPUTS[file_id] = path
    return file_id

@router.get("/files/{file_id}")
def serve_file(file_id: str, range: str = Header(None)):
    """Range-aware file serving. WaveSurfer issues range requests when
    the user clicks somewhere in the waveform — without range support,
    the whole file is re-fetched on every seek."""
    path = _OUTPUTS.get(file_id)
    if not path or not os.path.exists(path):
        raise HTTPException(404, "not found")

    file_size = os.path.getsize(path)
    if range is None:
        return FileResponse(path, media_type="audio/wav")

    # Parse "bytes=START-END"
    units, _, rng = range.partition("=")
    start_s, _, end_s = rng.partition("-")
    start = int(start_s) if start_s else 0
    end   = int(end_s) if end_s else file_size - 1
    end   = min(end, file_size - 1)
    length = end - start + 1

    def stream():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk: break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range":  f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges":  "bytes",
        "Content-Length": str(length),
    }
    return StreamingResponse(stream(), status_code=206,
                             media_type="audio/wav", headers=headers)
```

## 5. Frontend design

### 5.1 File structure

```
src/
├── main.tsx                ← React + Vite entrypoint; mounts <App>
├── App.tsx                 ← Top-level layout
├── styles/
│   ├── globals.css         ← Tailwind directives + CSS variables
│   ├── skin-default.css    ← Each skin = a [data-skin] CSS variable block
│   ├── skin-acid.css
│   └── skin-hardware.css
├── lib/
│   ├── api.ts              ← Typed fetch wrappers around the backend
│   ├── sse.ts              ← Tiny SSE helper (EventSource wrapper)
│   └── utils.ts            ← shadcn's cn() + format helpers
├── stores/
│   ├── slurmStore.ts       ← Zustand: input/output files, params, job state
│   ├── fxStore.ts          ← Zustand: FX chain params, FX preview state
│   └── skinStore.ts        ← Zustand: active skin, persisted to localStorage
├── hooks/
│   ├── useFxChain.ts       ← Web Audio FX chain (TypeScript port of INIT_JS)
│   ├── useSlurmifyJob.ts   ← Submit + stream progress + receive output
│   └── useFilePicker.ts    ← Drag-drop + file-input glue
├── components/
│   ├── ui/                 ← shadcn-installed: button, slider, dialog, …
│   ├── Header.tsx          ← Logo + skin picker + version tag
│   ├── DropZone.tsx        ← Universal upload (audio/video)
│   ├── WaveformPlayer.tsx  ← <Waveform>; bridges WaveSurfer + FX chain
│   ├── SlurmControls.tsx   ← Speed, resolution, transient, envelope
│   ├── SlurmifyButton.tsx  ← The "go" button + progress UI
│   ├── BeatMaskStrip.tsx   ← Per-bar chip strip (ADR-0019 port)
│   ├── UnitToggle.tsx      ← ms ⇄ ♪ chip toggle (ADR-0020 port)
│   ├── FxPanel.tsx         ← Distortion / RingMod / Delay / Phaser
│   ├── FxKnob.tsx          ← Reusable rotary knob (replaces sliders)
│   ├── XYPad.tsx           ← Optional: ring/phaser as 2D pads
│   ├── VideoExportPanel.tsx
│   └── DancerSplash.tsx    ← Replaces the Gradio dancer; now error-safe
└── types/
    └── slurm.ts            ← TypeScript types: SlurmParams, FxParams, JobStatus
```

### 5.2 Zustand store (slurmStore.ts)

```ts
import { create } from "zustand"
import { persist } from "zustand/middleware"

export interface SlurmParams {
  speed: number
  resolution: string
  transientSensitivity: number
  envelopeMs: number
  preservePitch: boolean
  pitchShiftSemitones: number
  randomizeOrder: boolean
  reverseChance: number
  stutterChance: number
  stutterSkipMs: number
  stutterMaxReps: number
  stutterSpread: number
  beatTrimStartMs: number
  beatTrimEndMs: number
  beatGapMs: number
  bpmOverride: number | null
  startSec: number
  endSec: number
  seed: number | null
  beatMask: boolean[] | null
  // ADR-0020 note-mode counterparts
  stutterSkipMode: "ms" | "♪"
  stutterSkipNote: string
  beatTrimStartMode: "ms" | "♪"
  beatTrimStartNote: string
  beatTrimEndMode: "ms" | "♪"
  beatTrimEndNote: string
  beatGapMode: "ms" | "♪"
  beatGapNote: string
  outputFormat: "wav" | "mp3" | "flac" | "ogg" | "aiff" | "aac"
}

interface SourceFile { id: string; url: string; name: string; durationSec: number }
interface SlurmOutput { id: string; url: string }

interface SlurmStore {
  source: SourceFile | null
  output: SlurmOutput | null
  params: SlurmParams
  jobId: string | null
  progress: number   // 0-1
  progressDesc: string
  isRunning: boolean
  error: string | null

  setSource: (s: SourceFile | null) => void
  setOutput: (o: SlurmOutput | null) => void
  setParam: <K extends keyof SlurmParams>(k: K, v: SlurmParams[K]) => void
  startJob: (id: string) => void
  updateJob: (p: { progress: number; desc: string }) => void
  finishJob: (output: SlurmOutput | null, error: string | null) => void
}

export const useSlurmStore = create<SlurmStore>()(
  persist(
    (set) => ({
      source: null,
      output: null,
      params: defaultSlurmParams(),
      jobId: null,
      progress: 0,
      progressDesc: "",
      isRunning: false,
      error: null,
      setSource: (s) => set({ source: s }),
      setOutput: (o) => set({ output: o }),
      setParam: (k, v) => set((s) => ({ params: { ...s.params, [k]: v } })),
      startJob:  (id) => set({ jobId: id, isRunning: true, progress: 0, progressDesc: "", error: null }),
      updateJob: (p)  => set({ progress: p.progress, progressDesc: p.desc }),
      finishJob: (o, e) => set({ isRunning: false, output: o, error: e, progress: o ? 1 : 0 }),
    }),
    {
      name: "slurm-store-v1",
      partialize: (s) => ({ params: s.params }),   // only persist params, not transient state
    }
  )
)
```

### 5.3 useFxChain — TypeScript port of INIT_JS Web Audio chain

This is the trickiest port because the v0.1.6 INIT_JS Web Audio chain is
~250 lines of carefully-tuned imperative code with the
`createMediaElementSource`-once invariant (ADR-0003). We carry that
invariant forward — same lifecycle, cleaner shape.

```ts
// src/hooks/useFxChain.ts
import { useEffect, useRef } from "react"
import type { FxParams } from "../types/slurm"

export function useFxChain(audioEl: HTMLAudioElement | null, params: FxParams) {
  const ctxRef = useRef<AudioContext | null>(null)
  const nodesRef = useRef<{
    src: MediaElementAudioSourceNode
    dist: WaveShaperNode
    ringOsc: OscillatorNode
    ringGain: GainNode
    delay: DelayNode
    delayFb: GainNode
    delayMix: GainNode
    phase: BiquadFilterNode[]
    phaseLfo: OscillatorNode
    analyser: AnalyserNode
  } | null>(null)

  // ─── Build the chain exactly once per audioEl ────────────────────────
  useEffect(() => {
    if (!audioEl) return
    // ADR-0003: createMediaElementSource is one-shot per <audio> element.
    // Use a data-attribute as the bind marker so we never double-bind.
    if (audioEl.dataset.fxBound === "1") return

    const ctx = new AudioContext()
    const src = ctx.createMediaElementSource(audioEl)

    const dist = ctx.createWaveShaper()
    dist.curve = makeDistortionCurve(0)   // initially flat
    dist.oversample = "4x"

    const ringOsc  = ctx.createOscillator()
    const ringGain = ctx.createGain()
    ringOsc.frequency.value = 200
    ringOsc.connect(ringGain.gain)
    ringOsc.start()
    ringGain.gain.value = 1   // depth = 0 means gain stays at 1

    const delay     = ctx.createDelay(2.0)
    const delayFb   = ctx.createGain()
    const delayMix  = ctx.createGain()
    delay.delayTime.value = 0.3
    delayFb.gain.value = 0
    delayMix.gain.value = 0

    const phase = [200, 600, 1200, 2400].map(fc => {
      const ap = ctx.createBiquadFilter()
      ap.type = "allpass"
      ap.frequency.value = fc
      return ap
    })
    const phaseLfo = ctx.createOscillator()
    phaseLfo.frequency.value = 1
    phaseLfo.start()

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024

    // Connect the dry path: src → dist → ringGain → delay → phase[0..3] → analyser → out
    let n: AudioNode = src
    n = n.connect(dist)
    n = n.connect(ringGain)
    n = n.connect(delay)
    delay.connect(delayFb)
    delayFb.connect(delay)            // feedback loop
    n = n.connect(delayMix)
    for (const ap of phase) n = n.connect(ap)
    n = n.connect(analyser)
    n.connect(ctx.destination)

    audioEl.dataset.fxBound = "1"
    audioEl.addEventListener("play", () => ctx.resume())   // suspended on creation

    ctxRef.current = ctx
    nodesRef.current = { src, dist, ringOsc, ringGain, delay, delayFb, delayMix, phase, phaseLfo, analyser }

    return () => {
      ctx.close()
      delete audioEl.dataset.fxBound
      ctxRef.current = null
      nodesRef.current = null
    }
  }, [audioEl])

  // ─── Apply params on every change (cheap; no rebuild) ───────────────
  useEffect(() => {
    const n = nodesRef.current
    if (!n) return
    n.dist.curve = makeDistortionCurve(params.distDrive)
    n.ringOsc.frequency.value = params.ringFreq
    n.ringGain.gain.value = 1 - params.ringDepth + params.ringDepth * 1   // gain swings 0–2 at depth=1
    n.delay.delayTime.value = params.delaySec
    n.delayFb.gain.value = params.delayFb
    n.delayMix.gain.value = params.delayMix
    n.phaseLfo.frequency.value = params.phaseRate
    // depth = 0 disables; for now treat as a static sweep amount
    for (let i = 0; i < n.phase.length; i++) {
      const fc0 = [200, 600, 1200, 2400][i]
      n.phase[i].frequency.value = fc0   // could be modulated by phaseLfo via gain node
    }
  }, [params])

  return { analyser: nodesRef.current?.analyser ?? null }
}

function makeDistortionCurve(drive: number): Float32Array {
  // tanh shaper, matches slurmcore._fx_distortion exactly
  const k = 1 + drive * 29
  const samples = 4096
  const curve = new Float32Array(samples)
  for (let i = 0; i < samples; i++) {
    const x = (i / samples) * 2 - 1
    curve[i] = Math.tanh(x * k) / Math.tanh(k)
  }
  return curve
}
```

### 5.4 WaveformPlayer — bridge WaveSurfer to the FX chain

```tsx
// src/components/WaveformPlayer.tsx
import { useRef } from "react"
import { useWavesurfer } from "@wavesurfer/react"
import { useFxChain } from "../hooks/useFxChain"
import { useFxStore } from "../stores/fxStore"

export function WaveformPlayer({ url, variant }: { url: string; variant: "input" | "output" }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const fxParams = useFxStore((s) => s.params)

  const { wavesurfer, isReady, isPlaying, currentTime } = useWavesurfer({
    container: containerRef,
    url,
    waveColor: "var(--slurm-cyan)",
    progressColor: "var(--slurm-orange)",
    cursorColor: "var(--slurm-rose)",
    height: 80,
    barWidth: 2, barGap: 1, barRadius: 1,
    normalize: true,
  })

  // Bind the FX chain only to the OUTPUT player (not the input).
  // wavesurfer.getMediaElement() returns the <audio> ws is using internally.
  const audioEl = isReady && variant === "output"
    ? wavesurfer?.getMediaElement() ?? null
    : null
  useFxChain(audioEl, fxParams)

  return (
    <div className="space-y-2">
      <div ref={containerRef} className="rounded border border-slurm-border bg-slurm-surface" />
      <div className="flex gap-2 items-center text-xs text-slurm-rose">
        <button
          onClick={() => wavesurfer?.playPause()}
          className="px-2 py-1 rounded bg-slurm-surface2 hover:bg-slurm-surface"
        >
          {isPlaying ? "⏸" : "▶"}
        </button>
        <span className="font-mono">{formatTime(currentTime)}</span>
      </div>
    </div>
  )
}

function formatTime(s: number) {
  const m = Math.floor(s / 60), r = (s % 60).toFixed(2)
  return `${m}:${r.padStart(5, "0")}`
}
```

### 5.5 SSE consumer — useSlurmifyJob

```ts
// src/hooks/useSlurmifyJob.ts
import { useCallback } from "react"
import { useSlurmStore } from "../stores/slurmStore"
import { paramsToRequest } from "../lib/api"

const BACKEND_URL = "http://localhost:" + (window as any).__SLURM_PORT__

export function useSlurmifyJob() {
  const { source, params, startJob, updateJob, finishJob, setOutput } = useSlurmStore()

  const run = useCallback(async () => {
    if (!source) return
    const res = await fetch(`${BACKEND_URL}/slurmify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(paramsToRequest(source.id, params)),
    })
    const { job_id } = await res.json()
    startJob(job_id)

    const es = new EventSource(`${BACKEND_URL}/jobs/${job_id}/progress`)
    es.onmessage = (ev) => {
      const j = JSON.parse(ev.data)
      updateJob({ progress: j.progress, desc: j.desc })
      if (j.done) {
        es.close()
        if (j.error) {
          finishJob(null, j.error)
        } else {
          finishJob({ id: j.output_id, url: `${BACKEND_URL}/files/${j.output_id}` }, null)
          setOutput({ id: j.output_id, url: `${BACKEND_URL}/files/${j.output_id}` })
        }
      }
    }
    es.onerror = () => { es.close(); finishJob(null, "SSE connection lost") }
  }, [source, params, startJob, updateJob, finishJob, setOutput])

  return run
}
```

`window.__SLURM_PORT__` is set by Tauri at app startup — see §6.

## 6. Tauri integration

### 6.1 tauri.conf.json (the relevant pieces)

```json
{
  "productName": "SIENA Slurmer",
  "version": "0.2.0",
  "identifier": "com.subvoyant.siena.slurmer",
  "build": {
    "beforeDevCommand":   "pnpm dev",
    "beforeBuildCommand": "pnpm build",
    "devUrl":             "http://localhost:1420",
    "frontendDist":       "../dist"
  },
  "app": {
    "windows": [{
      "title": "SIENA Slurmer",
      "width": 1280, "height": 860,
      "minWidth": 980, "minHeight": 700,
      "resizable": true,
      "fileDropEnabled": true
    }]
  },
  "bundle": {
    "active": true,
    "targets": ["dmg"],
    "icon": ["icons/icon.icns"],
    "macOS": {
      "minimumSystemVersion": "11.0",
      "entitlements": "entitlements.plist",
      "signingIdentity": "Developer ID Application: …",
      "providerShortName": "…"
    },
    "externalBin": ["binaries/slurmify-server"]
  }
}
```

`binaries/slurmify-server` is the PyInstaller-built backend, named with
the target triple suffix Tauri requires (e.g.
`slurmify-server-aarch64-apple-darwin`).

### 6.2 main.rs — spawn sidecar, parse port, expose to JS

```rust
// src-tauri/src/main.rs
use tauri::{Manager, Emitter};
use tauri_plugin_shell::{ShellExt, process::CommandEvent};
use serde_json::Value;

#[tauri::command]
async fn get_backend_port(window: tauri::Window) -> Result<u16, String> {
    // The sidecar prints {"slurmify_ready": true, "port": N} on its first
    // stdout line. We parse and return the port to the frontend.
    let sidecar = window.app_handle().shell().sidecar("slurmify-server")
        .map_err(|e| e.to_string())?;
    let (mut rx, _child) = sidecar.spawn().map_err(|e| e.to_string())?;

    while let Some(event) = rx.recv().await {
        if let CommandEvent::Stdout(bytes) = event {
            let line = String::from_utf8_lossy(&bytes);
            for chunk in line.lines() {
                if let Ok(v) = serde_json::from_str::<Value>(chunk) {
                    if let Some(p) = v["port"].as_u64() {
                        return Ok(p as u16);
                    }
                }
            }
        }
    }
    Err("backend never reported a port".into())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![get_backend_port])
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            // Don't block setup; spawn the port-fetch in the background and
            // emit it to the frontend when ready.
            tauri::async_runtime::spawn(async move {
                match get_backend_port(window.clone()).await {
                    Ok(port) => { let _ = window.emit("backend-ready", port); }
                    Err(e)   => { let _ = window.emit("backend-error", e); }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running tauri application");
}
```

The frontend listens for the `backend-ready` event:

```ts
// src/main.tsx (excerpt)
import { listen } from "@tauri-apps/api/event"
listen<number>("backend-ready", (e) => {
  (window as any).__SLURM_PORT__ = e.payload
  document.dispatchEvent(new CustomEvent("slurm:backend-ready"))
})
```

### 6.3 PyInstaller bundling for the sidecar

The existing `slurmify.spec` becomes the basis for the sidecar build.
Two key changes:

1. The entrypoint is `src-python/server.py`, not `app.py`.
2. Output binary is named with the target triple Tauri expects:
   `slurmify-server-aarch64-apple-darwin` (or `x86_64-apple-darwin`).

A small `build-sidecar.sh` wrapper handles the rename + copy into
`src-tauri/binaries/`. It also signs the sidecar binary (separately from
the Tauri app) using the same Developer ID — required for hardened
runtime to load it.

### 6.4 entitlements.plist additions

Carry over the existing entitlements and add:

```xml
<key>com.apple.security.cs.allow-jit</key>
<true/>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key>
<false/>
<key>com.apple.security.cs.disable-library-validation</key>
<true/>
```

`disable-library-validation` is needed for the Tauri shell to spawn a
PyInstaller binary; without it, hardened runtime blocks the child
process load.

## 7. Borrowable open-source references

These are projects worth reading before re-inventing parts of our stack.

| Project                             | What we borrow                                         | License | Notes |
|-------------------------------------|--------------------------------------------------------|---------|-------|
| **shadcn/ui**                       | Component primitives (Slider, Tabs, Toggle, Dialog)    | MIT     | Not a dep — install via CLI, code copied into our repo |
| **wavesurfer.js examples**          | Patterns for spectrogram, regions, hover plugins       | BSD-3   | https://wavesurfer.xyz/examples |
| **BBC peaks.js**                    | Inspiration for slice-grid editor (Phase 8 future work)| LGPL    | Don't import; just study the API |
| **BBC audiowaveform**               | Pre-decoded peaks for very long files                  | GPL-3   | License-compatible with us; can shell out to it for >10-min uploads |
| **Tauri React TypeScript template** | Project scaffold + tauri.conf.json defaults            | MIT     | `pnpm create tauri-app --template react-ts` |
| **Audapolis** (bugbakery)           | Tauri/Electron + Python audio editor architecture       | AGPL    | Read for ideas; don't import (license-incompatible with our GPL-3) |
| **react-knob-headless**             | Accessible rotary knob primitive                       | MIT     | Headless, we style it |
| **react-aria** components           | Drag-drop, keyboard navigation, focus rings            | Apache  | shadcn already pulls Radix which covers most of this |
| **Tone.js**                         | Higher-level Web Audio abstractions                    | MIT     | Optional. Our chain is hand-rolled and small enough that Tone might be overkill, but useful for future synths/sequencers |
| **framer-motion**                   | Skin-transition animations, dancer animation           | MIT     | Replaces the `siena_dancer.gif` with proper React animation |

License note: we're GPL-3.0. AGPL-only deps are off-limits (would force
the whole app to AGPL). MIT/BSD/Apache deps are fine. LGPL is fine for
linking but we should prefer permissive where possible.

## 8. Decision log

Each row is a choice we've explicitly made vs. alternatives, with the
reasoning so future-us / future-agents don't relitigate.

| # | Decision | Alternative considered | Rationale |
|---|----------|------------------------|-----------|
| D1 | Tauri 2 (not Electron) | Electron | Smaller bundle (~5 MB shell vs ~150 MB for Electron); native macOS WebView; better Apple Silicon perf. Same DMG distribution model we have today. |
| D2 | React 19 (not Svelte) | Svelte / Vue | Larger creative-tool ecosystem (wavesurfer-react, react-knob, react-rnd, peaks-react). Familiar patterns from any frontend hire. Svelte is faster but the ecosystem gap matters more for us. v19 specifically (decision 2026-05-08). |
| D3 | TypeScript (not plain JS) | Plain JS | Audio types and DSP params benefit massively from compile-time checks. Matches the discipline we already have in slurmcore's docstrings. |
| D4 | Vite (not webpack/Next) | webpack, Next.js, Remix | Tauri's official scaffolds use Vite. Fast HMR is critical for iterating on FX UI. Next/Remix add SSR overhead we don't need (this is a desktop app, not a web SPA). |
| D5 | shadcn/ui + Tailwind (not Mantine, MUI, Chakra) | Mantine, MUI, Chakra UI | shadcn copies primitives into our repo so we can theme them deeply without fighting a vendor lock-in. Matches our existing dark/compact aesthetic. Skin variants via Tailwind's `data-skin:` modifier are clean. |
| D6 | Zustand (not Redux/Recoil/Jotai) | Redux Toolkit, Recoil, Jotai | Smallest API surface. No Provider tree. Persist middleware handles localStorage cleanly. Our state is a flat record of params + UI flags; no normalization needed. |
| D7 | FastAPI (not Flask, aiohttp, BentoML) | Flask, aiohttp, plain ASGI | Already proven on the slurmcore stack (Gradio uses FastAPI internally). Pydantic models give us typed request payloads matching the TypeScript types one-for-one. |
| D8 | Localhost HTTP + SSE (not Tauri commands, not WebSocket) | Tauri commands, WebSocket | HTTP is debuggable in browser devtools; Tauri commands require Rust glue per endpoint. SSE is one-way and we never need server→client RPCs other than progress, so WS is overkill. |
| D9 | PyInstaller sidecar (not embedded Python, not Pyodide) | Embedded CPython, Pyodide/WASM | We already have PyInstaller working + signed + notarized in v0.1.6. Pyodide can't run librosa/pyrubberband (they need the rubberband CLI binary). |
| D10 | Random port at startup (not fixed port 7860) | Fixed port | Avoids "port in use" errors when slurmify is already running, when other dev servers grab 7860, or when running multiple instances. Random port is published via stdout for the Tauri shell to capture. |
| D11 | wavesurfer.js v7 (not Howler.js, not native HTML <audio>) | Howler.js, plain `<audio>` | We've already been using WaveSurfer through Gradio — the waveform UX is what users expect. v7 has a clean React wrapper and supports the Web Audio integration we need. |
| D12 | Skin via `data-skin` + CSS variables (not multiple stylesheets) | Multiple stylesheets, CSS-in-JS theming | Same model as v0.1.6 (ADR-0007); proven pattern. CSS variables in `:root[data-skin="acid"] { --slurm-cyan: …; }` blocks. |
| D13 | Persist params to localStorage (not to disk via Tauri fs) | Tauri filesystem persistence | localStorage is per-app and survives reloads; we don't need to share state with other apps or expose a "patch file" yet. Tauri fs API is available if Phase 8 wants patch save/load. |
| D14 | Skip Phase 6 entirely (do not bundle creative features into Gradio first) | Phase 6 in Gradio, then migrate | Every Phase 6 feature would be rewritten in the migration. Building once on the new stack is cheaper than building twice. The dancer-stuck-on-error bug (Phase 5) is one exception — we'll either ship a v0.1.7 patch or accept it dies with v0.1.6. **Recommendation:** ship v0.1.7 with the dancer fix as a 30-min side task, then begin migration. |
| D15 | Keep slurmcore + slurmio verbatim (no changes during migration) | Refactor slurmcore alongside the migration | Concurrency risk: changing the DSP and the UI simultaneously means failures are hard to localize. Freeze slurmcore at v0.1.6 for the migration; revisit after v0.2.0 ships. |
| D16 | macOS-only for v0.2.0 (not cross-platform) | Linux + Windows from day one | Keeps PyInstaller / signing / notarization within the platform we already have working. Tauri natively supports cross-platform; we add Linux + Windows targets as Phase 9 work. |
| D17 | Same Apple Developer ID for both binaries | Two separate certs | Simpler. The Tauri app bundle and the sidecar binary are signed in the same step using the same identity. |
| D18 | No auto-updater in v0.2.0 | Tauri's updater plugin from day one | Updater adds complexity (signed update manifests, hosted update server). Manual DMG distribution is fine for the beta tester crowd. Add updater in Phase 9. |

## 9. Migration sequence — week-by-week

Each week ends with a shippable checkpoint. If we have to pause the
migration, we always have a working state to come back to.

### Week 1 — Backend scaffolding

**Goal:** Python sidecar that runs slurmify via curl. No frontend yet.

- Create `src-python/` with `server.py`, `api/` modules per §4.1.
- Implement `/health`, `/upload`, `/slurmify`, `/jobs/{id}/progress`,
  `/files/{id}` per §4.2.
- Slurmcore + slurmio imported as-is from the existing files.
- Manual test: `curl -F file=@track.wav localhost:PORT/upload`,
  then POST a slurmify request, then SSE-tail progress, then GET
  the output file.

**Checkpoint:** working API. Existing Gradio UI still ships.

### Week 2 — Tauri shell + React skeleton

**Goal:** A native window opens, frontend shows a "backend connected"
indicator, an "upload" button works end-to-end through the sidecar.

- `pnpm create tauri-app --template react-ts` → scaffold `src/`,
  `src-tauri/`, package.json, tsconfig.
- Wire up Tauri sidecar config (§6.1, §6.2). PyInstaller-build
  the sidecar via a new `build-sidecar.sh`.
- Install Tailwind, shadcn/ui CLI, base components (Button, Slider,
  Card, Tabs, Toggle).
- Stand up Zustand stores per §5.2. Build `App.tsx` with a header,
  a DropZone, and a "running" indicator that turns green when the
  `backend-ready` event fires.
- Implement upload flow: drag-drop → `POST /upload` → store
  `source` → render a basic waveform with `useWavesurfer`.

**Checkpoint:** native app, drag a file in, see the waveform. No
slurmify yet.

### Week 3 — Slurmify pipeline + progress + waveform output

**Goal:** Click "slurmify", get a slurm output, play it back.

- Implement `useSlurmifyJob` per §5.5 (SSE progress consumer).
- Build `SlurmControls.tsx` with shadcn Sliders for the 12 main params.
- Build `BeatMaskStrip.tsx` (port of ADR-0019 chip strip).
- Build `UnitToggle.tsx` (port of ADR-0020 ms ⇄ ♪ toggle).
- Render the output waveform in a second `WaveformPlayer`.
- Display progress (shadcn Progress + the "Done", "Time-stretching…"
  step descriptions).

**Checkpoint:** feature parity for the core slurmify path. No FX yet.

### Week 4 — FX chain + skins

**Goal:** FX preview works in the browser, FX burn works via the
backend, all three skins look right.

- Implement `useFxChain` per §5.3 — full TypeScript port of the
  v0.1.6 INIT_JS Web Audio chain.
- Build `FxPanel.tsx` with FxKnob components.
- Build `/burn-fx` endpoint (mirrors `/slurmify` with `apply_fx`).
- Implement skin system per §5.1: `globals.css` with CSS variable
  defaults, three `skin-*.css` files toggled by `body[data-skin]`.
- Skin picker in header; persist to localStorage.

**Checkpoint:** FX preview + burn working. Skin variants render.

### Week 5 — Video export + polish + native niceties

**Goal:** YouTube MP4 export works. Native menu bar (File → Open,
Edit → Undo, Window controls, About). Drag-drop file onto the dock
icon opens it. App remembers window size.

- Implement `/render-video` endpoint (port `render_video`).
- Build `VideoExportPanel.tsx`.
- Add Tauri native menu via Rust config.
- File-association: open `.wav`/`.mp3` files via Finder.
- Replace Siena dancer GIF with a Framer Motion animation that's
  error-safe (mounts/unmounts based on `isRunning` flag — never
  stuck).

**Checkpoint:** feature parity with v0.1.6 + the polish improvements.

### Week 6 — Code signing, notarization, DMG, beta release

**Goal:** Signed, notarized DMG that runs from /Applications.

- Update `build.sh` (or replace with `build-tauri.sh`) to invoke
  `pnpm build` + `tauri build` + sign-sidecar + notarize + DMG.
- Verify hardened runtime works with the spawned sidecar.
- Smoke test on a clean Mac (or fresh user account) that doesn't
  have the dev environment.
- Write `SLURMER_BETATEST_INSTRUCTIONS.md` v0.2.0 section.
- Tag `v0.2.0`, ship DMG.

**Checkpoint:** v0.2.0 in the wild. Gradio archived to
`gradio-archive` branch.

### Optional Week 7+ — Features only the new architecture enables

The features we held back from Phase 6 because they'd be wasted
work in Gradio:

- **XY pads** for ring-mod and phaser (§3.1 of UI_DEVELOPMENT_PLAN).
- **A/B player** with click-toggle audible source (§2.5).
- **Spectrogram overlay** using the existing AnalyserNode (§3.2).
- **Rotary knobs** replacing FX sliders (proper creative-tool feel).
- **Slice-grid visualizer** — preview detected slice boundaries on
  the input waveform before running (§3.3).
- **FX presets** with localStorage save/load (§2.4).
- **Native file picker** for input + output paths.
- **Patch save/load** — full param state to a `.slurm` JSON file.

Each of these is a 3–8 hour task on the new stack vs days in Gradio.

## 10. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **PyInstaller startup latency** (2–4 s before backend is ready) | High | Medium | Show splash screen with progress; spawn sidecar eagerly during Tauri setup. The frontend already gates the UI on the `backend-ready` event. |
| **Port conflicts on launch** | Medium | Low | Use random port from `find_free_port()` (§4.3). |
| **Code signing the sidecar binary** | High | High | Sign with `--options runtime` + `disable-library-validation` entitlement (§6.4). Build script signs both binaries before notarization. Test on a clean Mac before release. |
| **Hardened runtime blocks child process load** | Medium | High | `disable-library-validation` entitlement covers it. Verified pattern in similar Tauri+Python apps. |
| **CORS between `tauri://localhost` and the sidecar** | Low | Low | Permissive CORS in dev; explicit origin allowlist in prod (§4.3). |
| **`createMediaElementSource` double-binding when components unmount** | Medium | High (silent FX failure — ADR-0003) | `audioEl.dataset.fxBound` guard + cleanup in useEffect (§5.3). Tested manually + this hook lifecycle is React-standard. |
| **wavesurfer.getMediaElement() returns null** before isReady | Medium | Low | Already guarded in `WaveformPlayer.tsx` via the `isReady && audioEl` check. |
| **HTTP range requests** for large stereo WAVs (>50 MB) | Low | Medium | §4.5 implements the range header parser. |
| **DMG bundle size** ~ 200 MB (Python + libs + Tauri) | Certain | Low | Acceptable for a creative tool. Document in betatest notes. Could be reduced later by building librosa from source minus optional features. |
| **Apple silicon vs intel** | Low | Medium | Build separate sidecars for each arch; `lipo` to make a universal binary; Tauri picks the right one. |
| **Migration takes longer than 6 weeks** | Medium | Medium | Each week's checkpoint is shippable in some form; if Week 4 slips, we still have a v0.2.0-alpha that does slurmify but no FX. |
| **Beta testers reject the new UI** | Low | High | Mitigation: don't break existing v0.1.6 DMG. Ship v0.2.0 alongside; let testers compare. Roll back if reception is bad. |
| **Frontend hot-reload doesn't survive Tauri restarts** | Low | Low | Vite + Tauri dev mode handles this; documented pattern. |
| **WaveSurfer v7 doesn't expose Web Audio enough** | Low | High | Confirmed by docs (§3 wavesurfer.xyz/examples/?webaudio.js — `getMediaElement()` returns the underlying element). Already a known-working pattern in v0.1.6. |

## 11. Rollback plan

If the migration fails halfway:

1. **The Gradio v0.1.6 codebase is preserved.** Before starting Week 1,
   create a `gradio-archive` branch from `main`. The migration happens
   on `main`. If we have to abandon, `git reset --hard gradio-archive`
   gets us back to a working v0.1.6 — no data loss.
2. **Slurmcore + slurmio never change.** Even if the entire UI rewrite
   is abandoned, the DSP engine continues to work in the Gradio version
   without modification.
3. **Partial migration is shippable.** Each week's checkpoint produces
   a working state. If Week 4 (FX chain) fails badly, we can still ship
   v0.2.0-alpha with slurmify but no FX, and route users to the v0.1.6
   DMG for FX work until the new chain is fixed.
4. **The DSP layer is the real value.** Slurmify the algorithm is
   captured in slurmcore.py; slurmify the user interface is rebuildable.
   We never lose the algorithmic work.

## 12. Decisions resolved before W1 start (2026-05-08)

All blocker-level open questions have been answered:

- **v0.1.7 dancer-fix patch:** **SKIPPED.** The dancer-stuck bug dies
  with v0.1.6 once v0.2.0 lands. Saves ~30 min of context-switching
  out of the migration.
- **React 18 vs 19:** **React 19.** New compiler, what new projects
  start with. wavesurfer-react 1.0.12 supports 19 explicitly.
- **Package manager:** **pnpm.** Faster, stricter, and what most new
  Tauri projects use.
- **Auto-updater:** **Deferred** to Phase 9 (matches D18). Beta
  testers get DMGs by hand for v0.2.0.

Non-blockers still deferred to the week they become relevant:

- **Native macOS menu bar** — File / Edit / Window / Help is the Apple
  standard. Skip the editor menu since we're not editing text? Decide
  in Week 5.
- **Telemetry / crash reporting** — none in v0.2.0; defer.
- **Multi-window (e.g. detached FX rack)** — Tauri supports it; defer.
- **Plugin system for community FX** — far future; no decision needed
  now beyond keeping `apply_fx` extensible.

## 12b. Pre-flight: rollback safety branch

**Before W1 begins**, the user runs the following to create the
rollback escape hatch (per §11 — never lose v0.1.6 in case the
migration goes sideways):

```bash
cd /Volumes/GrayMeta_VideoCRM114/CODE/slurmify && \
git checkout -b gradio-archive && \
git push -u origin gradio-archive && \
git checkout main
```

After this, `main` is the migration branch. If we ever need to
abandon, `git reset --hard origin/gradio-archive` restores the
working v0.1.6 codebase.

## 13. References

- [ADR-0003](0003-createmediaelementsource-once.md) — `createMediaElementSource`
  one-shot rule. Carries forward to the React `useFxChain` hook.
- [ADR-0007](0007-skin-system-data-skin.md) — `body[data-skin]` skin
  pattern. Carries forward; same approach in Tailwind.
- [ADR-0016](0016-slurmcore-dsp-extraction.md) — slurmcore purity rule.
  This ADR depends on slurmcore being completely UI-agnostic.
- [ADR-0017](0017-slurmio-filesystem-extraction.md) — slurmio purity
  rule. Same dependency.
- [ADR-0021](0021-stereo-end-to-end.md) — Channel-layout convention.
  The `.T` transpose at the soundfile boundary still applies in the new
  backend (§4.4).
- `docs/UI_DEVELOPMENT_PLAN.md` §4–§5 — the original sketch this ADR
  supersedes.
