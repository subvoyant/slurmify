# Slurmify

A chopped, sped-up, transient-sliced audio remixer. Drop in an audio file, twist some knobs, get a slurm-style remix back. Runs locally in your browser.

**Inputs:** mp3, wav, aif, aiff, aac, m4a, flac, ogg
**Output:** wav

---

## Setup (macOS)

You'll need three things: Python, FFmpeg (for non-wav input formats), and Rubber Band (for high-quality time-stretching). The easiest path is via [Homebrew](https://brew.sh/).

### 1. Install system dependencies

```bash
brew install python ffmpeg rubberband
```

- **python** — the runtime (3.10 or later recommended)
- **ffmpeg** — lets librosa read mp3/aac/m4a/etc.
- **rubberband** — the C library that `pyrubberband` wraps for pitch-preserving time-stretch

### 2. Set up a virtual environment

From inside the project folder:

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

Open that in your browser. Drop in audio, hit **slurmify**, listen.

To stop: `Ctrl+C` in the terminal.
To leave the venv when you're done: `deactivate`.

---

## Parameters

| Knob | What it does |
|---|---|
| **Speed multiplier** | How much faster than the original (1.0–4.0×). 2.0 is a typical slurm starting point. |
| **Slice resolution** | Grid spacing for slices, in note values. 1/16 is the canonical slurm feel; 1/32 gets more frantic. |
| **Transient sensitivity** | 0 = slices land on a pure tempo grid. 1 = slices snap to detected onsets in the audio. Middle values blend both. |
| **Slice envelope** | Tiny fade-in/out at slice edges. 0 ms = hard cuts (clicky, classic). 2–5 ms = smoother. |
| **Preserve pitch** | On = tempo changes but pitch stays put. Off = chipmunk effect (pitch rises with speed). |
| **Randomize slice order** | Shuffles all slices into random order before reassembly. |
| **Reverse chance per slice** | Probability each slice plays backwards. |
| **Stutter chance per slice** | Probability each slice repeats 2–4 times in place. |
| **Seed** | Optional. Set a number to make randomization reproducible. Leave blank for fresh chaos every run. |

---

## Tips for a good slurm sound

- Start with **speed 2.0**, **resolution 1/16**, **transient sensitivity 0.5**, **stutter 0.15**, everything else default. That's roughly the canonical recipe.
- Drop **envelope to 0** if you want classic clicky-edged slurm grit. Push it to 5–10ms for a smoother, more musical version.
- **Randomize order** off + **stutter on** preserves the song's shape but makes it stutter and gurgle. **Randomize order on** turns the input into pure texture.
- For non-percussive material (vocals, pads), **transient sensitivity 0.7+** tends to sound better — pure grid slicing on smooth audio is too mechanical.
- The **seed** field is your friend. Find a sound you like, lock the seed, then iterate other parameters around it.

---

## Notes

- Processing is **fully local** — nothing is uploaded anywhere. The Gradio UI runs on your own machine.
- Output is always 44.1 kHz, 16-bit wav. Convert to mp3 elsewhere if you need it smaller.
- The audio engine (`slurmify()` function in `app.py`) is independent of the UI. If you later want to wrap it in Electron or expose it as a REST API, you can call that function directly.

---

## Troubleshooting

**"No module named 'pyrubberband'"** — you forgot to activate the venv. Run `source .venv/bin/activate` first.

**"Failed to find Rubber Band Library"** — `brew install rubberband` was skipped, or your shell can't find it. Try `brew reinstall rubberband` and restart the terminal.

**"Could not load mp3"** — ffmpeg isn't installed or isn't on PATH. Run `brew install ffmpeg` and try again.

**Output sounds clipped/distorted** — try lowering speed, or turning down the stutter chance (overlapping repeats can pile up).

**It's slow** — librosa and rubberband are CPU-heavy. A 3-minute song typically takes 5–20 seconds depending on parameters. First run after install can be slower as Python compiles cached imports.
