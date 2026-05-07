# Slurmify — SIENA Slurmer

A chopped, time-stretched, transient-sliced audio remixer with a real-time FX
pedalboard and one-click YouTube video export. Drop in any audio or video file,
twist some knobs, get a slurmified remix back. Everything runs locally in your
browser — nothing leaves your machine.

**Audio inputs:** mp3, wav, aif, aiff, aac, m4a, flac, ogg, opus, wma, ape, alac  
**Video inputs:** mp4, mov, mkv, webm, wmv, flv, mpg, mpeg, m4v, 3gp (audio
is extracted automatically via ffmpeg)  
**Outputs:** wav, flac, ogg, aiff, mp3, aac — selected via the output format
dropdown

---

## Setup (macOS)

You need three things: Python, FFmpeg (for non-wav formats), and Rubber Band
(for high-quality time-stretching). The easiest path is [Homebrew](https://brew.sh/).

### 1. Install system dependencies

```bash
brew install python ffmpeg rubberband
```

- **python** — the runtime (3.10 or later recommended)
- **ffmpeg** — decodes mp3/aac/m4a and encodes mp3/aac output; also extracts
  audio from video files
- **rubberband** — the C library that `pyrubberband` wraps for
  pitch-preserving time-stretch

### 2. Set up a virtual environment

```bash
cd slurmify
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Run it

```bash
python app.py
```

You'll see something like:

```
Running on local URL:  http://127.0.0.1:7860
```

Open that URL in your browser, drop in audio, hit **slurmify**, listen.

To stop: `Ctrl+C` in the terminal.  
To leave the venv when you're done: `deactivate`.

---

## What it does

**Core pipeline:** takes any audio file, speeds it up, slices it into
fragments on a beat-aligned grid, optionally snaps slice boundaries to
detected musical onsets, then optionally shuffles, reverses, or stutters
individual slices before reassembling and normalising. The result is a
slurm-style remix.

**Real-time FX panel:** after slurmifying, open the **⚡ real-time FX**
accordion to audition a four-stage distortion → ring-mod → delay → phaser
chain live in the browser via the Web Audio API. Drag sliders while audio
plays — changes are instant. Hit **burn FX to file** to bake the current
settings into a new audio file.

**YouTube video export:** open the **🎬 export video for YouTube** panel,
enter a title and optional creator handle, choose the audio source (slurm
output or FX-burned), and hit **render YouTube MP4**. You get a 1280×720 MP4
with a looping Siena cell-animation and your audio. The MP4's metadata
carries the full patch as JSON — YouTube auto-fills title and description
from it.

---

## Parameters

### Slurmify controls

| Control | What it does |
|---|---|
| **Speed multiplier** | How much faster than the original (1.0–4.0×). 2.0 is a typical slurm starting point. |
| **Slice resolution** | Beat-subdivision grid for slices. 1/16 is the canonical slurm feel; 1/32 gets more frantic. MAX RANDOM bypasses the grid entirely — each slice is randomly drawn from three buckets: stutter (5–30 ms), chop (100–500 ms), or held (1–4 s). |
| **BPM override** | *(optional)* If librosa detects the wrong BPM octave (e.g. 70 instead of 140), enter the correct value here. Leave blank for auto-detect. |
| **Transient sensitivity** | 0 = slices land on a pure tempo grid. 1 = slices snap to detected audio onsets. Middle values blend both. |
| **Slice envelope (ms)** | Tiny fade-in/out at slice edges. 0 ms = hard cuts (clicky, classic). 2–5 ms = smoother. |
| **Preserve pitch** | On = tempo changes but pitch stays put. Off = chipmunk effect (pitch rises with speed). |
| **Pitch shift (semitones)** | Independent pitch shift in semitones, applied after time-stretching. 0 = no shift. |
| **Randomize slice order** | Shuffles all slices into random order before reassembly. |
| **Reverse chance** | Per-slice probability of playing backwards (0.0–1.0). |
| **Stutter chance** | Per-slice probability of looping. 0.15 is the default. |
| **Skip length (ms)** | When > 0, stutter loops only the first N ms of each slice instead of the whole slice (CD-skip effect). 0 = classic full-slice stutter. |
| **Max repetitions** | How many times each stuttered slice repeats (2–16). |
| **Spread** | 0 = every stutter uses the same skip length. 1 = each stutter picks a random head length between 0 and the skip value — organic variation. |
| **In / Out (seconds)** | Trim the input to a sub-range before slurmifying. Leave at 0 for full length. |
| **Seed** | Set a number to make randomization reproducible. Leave blank for fresh chaos every run. |
| **Output format** | wav, flac, ogg, aiff, mp3, or aac. |

### Real-time FX controls

| Control | What it does |
|---|---|
| **Drive** | Distortion amount (tanh waveshaper). 0 = clean. |
| **Ring freq (Hz)** | Ring modulator oscillator frequency. |
| **Ring depth** | Ring modulator mix depth. 0 = off. |
| **Delay (s)** | Delay line length in seconds. |
| **Delay feedback** | Amount of signal fed back into the delay loop. |
| **Delay mix** | Wet/dry blend for the delay. |
| **Phaser rate (Hz)** | LFO rate for the phaser sweep. |
| **Phaser depth** | Phaser sweep depth. 0 = off. |

---

## Tips for a good slurm sound

- **Classic recipe** — Speed: 2.0 · Resolution: 1/16 · Transient: 0.5 ·
  Stutter: 0.15 · Envelope: 2 ms · Preserve pitch: on · everything else default.
- Drop **envelope to 0** for classic clicky-edged slurm grit. Push it to
  5–10 ms for a smoother, more musical version.
- **Randomize order off** + **stutter on** preserves the song's shape but
  makes it stutter and gurgle. **Randomize order on** turns the input into
  pure texture.
- For non-percussive material (vocals, pads), **transient sensitivity 0.7+**
  tends to sound better — pure grid slicing on smooth audio is too mechanical.
- **MAX RANDOM** + **randomize order on** is the most chaotic setting. Each
  run is completely different. Lock a **seed** if you find something you like.
- **Skip length** in the 15–30 ms range on a 0.3–0.5 stutter chance gives the
  CD-stuck groove sound without being too abrasive.
- The **🎲 randomize all** button scrambles all parameters at once with
  musically-biased ranges — good for quick exploration.

---

## Skins

Three visual themes are available via the skin picker in the header:

| Skin | Description |
|---|---|
| **subvoyant · default** | Dark cyan look — the default. |
| **acid cathedral** | Psychedelic: animated rainbow title, glassmorphic panels, glowing slurmify button that reacts to audio. |
| **hardware rack** | Vintage analog-synth: brushed metal, knurled chrome sliders, LED checkboxes, amber LCD readouts, VU meter. |

Your choice persists between sessions. Share a specific look via URL:  
`http://127.0.0.1:7860/?skin=acid` · `?skin=hardware` · `?skin=default`

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| **I** | Set in-point (start trim) to current playhead position |
| **O** | Set out-point (end trim) to current playhead position |

---

## Workflow overview

1. **Drop in a file** — drag any audio or video file into the upload box (or
   the dedicated "drop a video / any media file" panel below it). The waveform
   appears in the audio player.
2. **Set in/out (optional)** — play the file, press **I** at the start of the
   section you want, **O** at the end.
3. **Adjust the controls** — or hit 🎲 to randomize everything.
4. **Hit slurmify** — processing takes roughly the same time as the audio's
   duration. A Siena dancer animation shows while it runs.
5. **Listen** — the output appears below. Download it, or continue to FX.
6. **FX panel (optional)** — open **⚡ real-time FX**, drag sliders while the
   output plays, then hit **burn FX to file**.
7. **Video export (optional)** — open **🎬 export video for YouTube**, fill in
   the title, choose the audio source, hit render. One click → YouTube-ready MP4.
8. **Grab your files** — click **📁 reveal temp files** to open the session
   folder in Finder. Everything in there is yours until you quit.

---

## Notes

- Processing is **fully local** — nothing is uploaded anywhere. The Gradio UI
  runs on your own machine and is only accessible at `127.0.0.1`.
- All output files live in a **session temp folder** that is automatically
  wiped when you quit. Use **📁 reveal temp files** to move anything you want
  to keep before quitting.
- The audio DSP engine (`slurmcore.py`) is independent of the UI. If you want
  to wrap it in a different interface or call it from another script,
  import `slurmify()` from `slurmcore` and `load_audio` / `_write_audio`
  from `slurmio` directly.

---

## Troubleshooting

**"No module named 'pyrubberband'"** — you forgot to activate the venv.
Run `source .venv/bin/activate` first.

**"Failed to find Rubber Band Library"** — `brew install rubberband` was
skipped, or your shell can't find it. Try `brew reinstall rubberband` and
restart the terminal.

**"Could not load mp3"** — ffmpeg isn't installed or isn't on PATH.
Run `brew install ffmpeg` and try again.

**Video file not loading** — make sure ffmpeg is installed (`brew install
ffmpeg`). Slurmify uses ffmpeg to extract the audio track from video files.

**Output sounds clipped/distorted** — try lowering stutter chance or skip
length. Stuttered slices that pile up can push peaks above unity before
normalization catches them.

**It's slow** — librosa and rubberband are CPU-heavy. A 3-minute song
typically takes 5–20 seconds depending on parameters. First run after install
can be slower as Python compiles cached imports.

**FX preview shows 0:00** — open browser DevTools (Cmd+Opt+J in Chrome) and
filter for `[slurm]` messages. The most common causes are: AudioContext
suspended (press Play on the FX preview player first) or INIT_JS not loading
(check that `ui.launch(head=...)` is intact in `app.py`).

**The app bundle shows "damaged" on first launch** — go to
**System Settings → Privacy & Security → Open Anyway**. This is a one-time
Gatekeeper prompt; the app is signed and notarized.

---

## System requirements

- macOS 13 Ventura or later (app bundle)
- Python 3.10 or later (dev mode)
- Any modern Mac — Intel or Apple Silicon
- A web browser (Chrome, Firefox, Safari, Edge — any modern browser)
