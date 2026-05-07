# Subvoyant SIENA Slurmer v0.1.4 — Beta Test Notes

Hi Person — thanks for testing the SIENA Slurmer. Here's everything you need to know.

---

## What's new in 0.1.4

A rhythmic control release: you can now selectively drop individual beat positions from the slurmify output — e.g. keep beats 1 and 3 of every bar, drop 2 and 4 — using a chip strip that appears below the resolution picker.

- **Beat mask chip strip.** A row of toggle chips appears for resolutions up to 1/16 (1, 2, 4, 8, or 16 chips depending on resolution). Labeled ①–⑯. Click a chip to drop that beat position from the output; click again to restore it. All chips on = no filtering, same output as before. The strip resets to all-on whenever you change resolution. Hidden for 1/32 and above (too dense to be useful) and for MAX RANDOM (no fixed grid to mask).
- **Beat mask is zero-overhead when not used.** If all chips are on, the filter step is skipped entirely — no performance impact on the default path.
- **Beat mask is preserved in the YouTube MP4 export.** The `PATCH=` JSON in the video description includes `core.bar_mask` so the pattern is fully reproducible.
- **Fix: beat mask chip strip now updates when resolution changes after a slurmify run.** Previously the chips would freeze at the last-built chip count once any slurmify had completed. Now the strip reliably rebuilds whenever you change the resolution.

---

## What's new in 0.1.3

A BPM detection upgrade: the slicer now follows the track's actual beat grid instead of drifting away from it on variable-tempo material, and there's a new control to correct the occasional octave error librosa makes.

- **Adaptive beat-grid slicing.** Previously, the slicer estimated one global BPM and laid down a perfectly uniform grid for the entire track. That grid drifts away from the audio whenever the tempo ramps, floats, or has any human feel. Now the slicer keeps the actual beat positions detected by librosa and subdivides or coarsens them per-interval — the grid bends with the song. On a dead-straight click track you won't hear a difference; on live drums or anything with tempo variation, slice boundaries land on real musical events instead of drifting a few ms out by the end of the track.
- **BPM override (optional).** New text field below the slice resolution picker. Leave it blank for auto-detect (same as before). Enter a number — e.g. `140` — if librosa guessed the wrong octave (e.g. detected 70 BPM on a 140 BPM track). The entered value is passed to the beat tracker as a starting hint so it anchors to the right tempo. The detected beat positions are still used for the adaptive grid; only the octave disambiguation changes.

---

## What's new in 0.1.2

A focused DSP release: the stutter engine gets three new controls that open up a qualitatively different sound — the "skippy" CD-stuck quality you hear in reference slurmcore tracks — while keeping the old full-slice stutter behavior at the default zero position.

- **Skip length (ms).** New slider below "stutter chance." At 0 (default), the stutter works exactly as before — the whole slice tiles. Raise it above zero and the stutter switches to *skip mode*: only the first N milliseconds of each slice are looped, creating the CD-skip / vinyl-stuck-groove sound. The sweet spot is around 20–40 ms for most material; 5–15 ms tips into glitch buzz territory.
- **Reps (max).** Replaces the internal hardcoded 2–4 repeat range with an exposed slider (2–16). Higher values → denser, more machine-gun stutter patterns. Works in both classic and skip modes.
- **Spread.** At 0, every stutter event uses the same skip length (uniform texture). Raise it toward 1 and each stutter picks its own random head length anywhere from nearly zero up to the set skip value — so a single output has tiny glitch blips, medium skips, and longer phrase stutters all mixed organically. Great for not sounding algorithmic.
- **Randomize all updated.** The 🎲 button now randomizes all three new stutter parameters with musically-biased ranges (skip_ms weighted toward 0, 15, 20, 25, 30; reps toward 4–8; spread toward 0–0.6).

---

## What's new in 0.1.1

A polish + small-features release on top of 0.1.0.

- **Header is now a link.** Click the Siena cat or the **SIENA SLURMER** title in the header — opens [subvoyant.com](https://www.subvoyant.com) in a new tab.
- **Bob easter egg.** Hover the **📁 reveal temp files** button and Bob springs up out of it with a bouncy animation. Bob suggested the feature.
- **Hoberman-Max easter egg.** Hover the **🎲 randomize all** button and Hoberman-Max pops up the same way. Two testers, two tribute gifs, matched motion.
- **Video / any-media file extraction.** A second drop zone below the audio input accepts any file — mp4, mov, mkv, wmv, webm, flv, etc. ffmpeg pulls the audio out automatically; the waveform appears in the input audio panel just as if you'd dropped a wav file. (The native audio-input zone still has the OS file-type filter — for video files, drop them in the new "…or drop a video / any media file" panel.)
- **SLURMCORE_COMPARISON.md included in the DMG.** A long-form guide explaining how Slurmify's method differs from general slurmcore practice, with sections for newcomers and engineers, a signal flow diagram, comparison table, and glossary.
- **Typography consistency.** The in/out and seed textboxes now use exactly the same font size and padding as every other text input in the app — no subtle 0.82rem-vs-0.8rem mismatch.
- **YouTube video correctly burns FX even without prior burn click.** Already shipped in 0.1.0 but worth restating: picking "FX-burned output" now auto-burns from current slider values if no burn file exists. No more silent dry-output renders.

---

## What's new in 0.1.0

A big features release — new slicing modes, lots of UI polish, and the kind of quality-of-life additions that make a difference once you start using it daily.

- **Nine slice resolutions instead of four.** Added **1/1** (whole-note slices spanning 4 beats), **1/2** (half-note), **1/64**, **1/128** (extreme micro-chops), and a new **MAX RANDOM** mode. The dropdown is now a tight chip row so all options are visible at once.
- **MAX RANDOM mode.** Bypasses the tempo grid entirely. Each slice's duration is independently random across three categorical buckets — **stutter** (5-30ms audio-rate blips), **chop** (100-500ms recognizable chunks), and **held** (1-4s long passages) — chosen 1/3 each so you hear genuinely chaotic gear-shifts: a 5ms stutter next to a 2-second held vowel next to a chop. Auto-enables the shuffle checkbox so it actually sounds chaotic. Hover the option for a special Max guest appearance.
- **🎲 Randomize all button.** Below the in/out bar. One click scrambles speed, slice resolution, transient sensitivity, envelope, pitch, reverse and stutter chances. Output format and in/out trim are preserved. Same Max gif hover as MAX RANDOM.
- **Drop ANY audio or video file.** Throw in mp4, mov, mkv, wmv, webm — audio extracted automatically. No more "unsupported format" wall when you've got a video clip you want to slurmify.
- **📁 Reveal temp files button.** Opens a Finder window showing the current session's temp folder so you can grab outputs before quit wipes them.
- **YouTube video correctly burns FX now.** Previously, picking "FX-burned output" in the video panel without first clicking "burn FX to file" silently rendered the dry slurm output. Now it auto-burns from the current slider values. Just works.
- **Session-scoped temp file cleanup.** All slurmify outputs, video exports, and intermediate files live in a per-session subdirectory now. On normal quit, the whole subdirectory is wiped — your disk gets every byte back. Crashed sessions are cleaned up on next launch. No more gigabytes of slurm files accumulating over weeks.
- **Compact UI everywhere.** Slice resolution as chip row, dropdowns match the dark theme (no more glaring white box), audio drop zones are smaller, info text is tighter. Vertical rhythm reclaimed across all three skins.
- **Tab icon = Siena cat.** (May need a browser hard-reload to refresh — browsers cache favicons aggressively.)
- **LICENSE in the DMG.** Full GPL-3.0 plus third-party notices for rubberband, ffmpeg/libx264, librosa, etc. The DMG also now includes the beta-test notes and a proper drag-to-Applications layout with the canonical Applications symlink.

---

## What's new in 0.0.9

A big release. Everything that came after 0.0.7 (which Bob and Max have already) is in here.

- **Skins.** New **`skin`** dropdown in the top-right of the header. Three to try:
  - **subvoyant · default** — the dark cyan look you already know.
  - **acid cathedral** — psychedelic. Animated rainbow title, hue-rotating gradient background, glassmorphic accordions, glowing slider thumbs, and the slurmify button glows along with the bass when audio is playing.
  - **hardware rack** — vintage analog-synth aesthetic. Brushed-metal panels, knurled chrome slider thumbs, LED-style checkboxes, LCD-amber numeric readouts, faux brass screws in every panel corner, and a real audio-reactive VU meter under the slurm output.
  
  Your choice is remembered between sessions. You can also share a specific look via URL: `http://127.0.0.1:7860/?skin=acid` etc.
- **YouTube-ready video export.** New **🎬 export video for YouTube** panel under the FX accordion. Renders a 720p MP4: looping VHS-aesthetic Siena animation (with `SUBVOYANT SIENA SLURMIFY` title and `www.subvoyant.com` URL baked into the frame) and your slurmified audio as the soundtrack. Render is essentially instant (the video is stream-copied from a pre-encoded loop, so only the audio gets re-encoded). A 3-minute song produces about a 35 MB file.
- **12 fps cell-animation dancer.** The Siena animation in the video runs at 12 fps — the classic "animation on twos" rate Disney and Warner Bros. used for everything hand-drawn. Reads as deliberately animated rather than choppy or jittery.
- **Self-describing files.** The MP4's metadata atoms carry the full slurm patch — every knob position plus the FX settings — as a JSON blob in the description. YouTube auto-fills the title and description on upload from those atoms.
- **`Subvoyant_Siena_Slurmify_…` naming.** Output filenames start with `Subvoyant_Siena_Slurmify_`, optionally include a sanitized version of your title, and end with a 16-character chaotic suffix derived from the original filename (shuffled and leet-transposed: e↔3, s↔5, o↔0, i↔1). When you set a slurmify seed, the suffix is reproducible — same seed, same anagram. No seed = fresh chaos every render.
- **Audio source choice for the video.** Render with the raw slurm output or the FX-burned version. FX-burned is the default since it's the final mix.
- **Privacy toggle.** "Include source filename in metadata" is off by default; the embedded patch JSON stays anonymous unless you opt in.
- **Tighter UI.** Smaller slider thumbs, less vertical padding, more controls visible at once without scrolling. Type sizes are unchanged.

---

## What's new in 0.0.7

- **Real-time FX preview pedalboard.** Open the **⚡ real-time FX** panel under the slurm output. The new "FX preview" player runs the slurm output through a live distortion → ring-mod → delay → phaser chain. Hit play and twist the sliders while it plays — changes are instant, no reprocessing.
- **Burn FX to file** is unchanged — it bakes the current slider values into a new audio file using the same DSP, so what you preview is what you export.
- Internal: previously the FX chain was wired but silent (Web Audio autoplay-policy + a `createMediaElementSource` re-binding bug). The preview now uses a dedicated audio element bound exactly once, with the AudioContext resumed on the play gesture.

---

## Installing

1. Open the **SubvoyantSIENASlurmer-0.1.4.dmg** file you received
2. Drag **Subvoyant SIENA Slurmer** into your **Applications** folder
3. Eject the DMG (drag it to Trash, or right-click → Eject)

> **First launch only:** macOS may show a warning that the app was "downloaded from the internet." If it does, go to **System Settings → Privacy & Security**, scroll down, and click **Open Anyway**. This is a one-time thing — the app is signed and notarized by Apple, macOS just asks once for newly downloaded apps.

---

## Launching

Double-click **Subvoyant SIENA Slurmer** in your Applications folder.

A browser tab will open automatically at `http://127.0.0.1:7860`. That's the app — it runs locally on your machine. **Your audio never leaves your computer.**

If the tab doesn't open after ~10 seconds, open your browser manually and go to `http://127.0.0.1:7860`.

---

## What It Does

Slurmify takes any audio file and chops it into tiny slices, speeds it up, and reassembles it — the "slurm" or "chopped and screwed" aesthetic you hear in a lot of hyperpop and internet-era remixes.

---

## How to Use It

1. **Drop in an audio file** using the upload box on the left. Any format works: mp3, wav, m4a, aiff, flac, ogg.
2. **Twist the knobs** (described below)
3. Hit **⟶ slurmify**
4. The output audio player appears at the bottom — hit play, or download it
5. *(optional)* Open the **⚡ real-time FX** panel and use the **FX preview** player to audition distortion / ring mod / delay / phaser on the slurm output in real time. Hit **⬇ burn FX to file** to bake the current settings into a new audio file.
6. *(optional)* Open the **🎬 export video for YouTube** panel, give your track a title (and your handle if you want it credited), and hit **🎥 render YouTube MP4**. The resulting MP4 has the Siena cell-animation loop, your audio, and the slurm patch metadata embedded — drop it on YouTube and the upload form pre-fills the title and description automatically.

### The Controls

| Knob | What it does |
|---|---|
| **Speed multiplier** | How much faster than the original. 2× is classic slurm. 4× gets very glitchy. |
| **Slice resolution** | How fine the chops are. 1/16 is a good starting point; 1/32 gets very granular. |
| **Transient sensitivity** | 0 = slices on a pure tempo grid. 1 = slices snap to the actual drum hits and note attacks. |
| **Slice envelope (ms)** | 0 = hard, clicky cuts (classic). Higher = smoother crossfades between slices. |
| **Preserve pitch** | On = speed up without chipmunk effect. Off = pitch rises with speed (try it on vocals). |
| **Randomize slice order** | Shuffles the slices into a random order — makes it chaotic and unpredictable. |
| **Reverse chance** | Probability each slice plays backwards. 0.1–0.2 adds subtle weirdness. |
| **Stutter chance** | Probability each slice repeats 2–4 times before moving on. 0.15 is the default. |
| **Seed** | Enter any number to get a reproducible result. Leave blank for random every time. |

### Suggested starting patches

**Classic slurm** — Speed: 2.0 · Resolution: 1/16 · Transient: 0.5 · Envelope: 2ms · Preserve pitch: on · Stutter: 0.15

**Glitch chaos** — Speed: 1.5 · Resolution: 1/32 · Transient: 0.8 · Envelope: 0ms · Preserve pitch: off · Randomize: on · Reverse: 0.2 · Stutter: 0.3

**Chipmunk chop** — Speed: 3.0 · Resolution: 1/8 · Preserve pitch: off · Stutter: 0.0

---

## Feedback We're Looking For

Anything you notice is useful — there are no wrong answers. Some specific things worth noting:

- **Does it actually launch and open the browser?** Any error messages on startup?
- **Does it work with the file formats you threw at it?** (mp3, m4a, wav etc.)
- **How does it sound?** Too clean? Too harsh? Interesting or boring?
- **Which knobs feel confusing or badly named?**
- **Is processing fast enough?** (It should take about the same time as the audio's duration at most)
- **Anything crash, hang, or produce silence when you expected audio?**
- **What's missing?** What would make you actually use this?

---

## Requirements

- macOS 13 Ventura or later
- Any modern Mac (Intel or Apple Silicon)
- A web browser (Safari, Chrome, Firefox — whatever you use)

---

## Quitting

Close the browser tab, then quit Slurmify from the Dock (right-click → Quit) or press **⌘Q** with the Dock icon selected.

---

*Subvoyant · Built with Python + Gradio · Runs 100% locally · v0.1.4 alpha*
