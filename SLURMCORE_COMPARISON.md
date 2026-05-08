# Slurmify vs. Slurmcore — How Subvoyant's Method Differs

A long-form comparison of the Subvoyant SIENA Slurmify method against the general
"slurmcore" approach as practiced across TikTok, YouTube, SoundCloud, and the
informal producer communities where the technique took root. Written for both
newcomers ("what *is* this thing?") and engineers ("what's actually happening
under the hood?"), with the technical depth in clearly-marked sections so you
can skim or dive in as you like.

---

## TL;DR

**Slurmcore**, as it's generally practiced, is a song-mangling technique where
producers take a finished track and chop it up into small chunks that play back
out of order, often combined with a global speed-up and a shifted pitch, to
produce a hypnotic, frantic, glitchy version of the original. The defining
sound is somewhere between a mashup, a vaporwave edit, and a stutter remix —
the song is recognizably itself, but it's been put through a blender.

The typical slurmcore workflow uses general-purpose DAWs (Ableton, FL Studio,
Audacity, Reaper) with manual chopping, beat-repeat plugins, and resample-based
speed-ups. The producer's ear is the main slicing instrument; the chopping is
hand-placed and often imprecise.

**Slurmify** is a local Python application (five focused modules, distributed
as a signed macOS `.app`) that automates and extends the slurmcore method with
the following deliberate departures:

1. **Pitch and tempo are independent controls** — not coupled by the resample.
2. **Slicing is beat-grid-aware** — BPM is detected and slices fall on note
   subdivisions (1/1, 1/2, ..., 1/128) instead of being placed by ear.
3. **Slicing is also transient-aware** — a slider hybrids between pure-grid
   and pure-onset detection, so chops can land on actual musical events.
4. **MAX RANDOM mode** — a trimodal distribution (stutter / chop / held)
   produces categorically-different slice durations no human would manually
   select, with reproducibility through a seed.
5. **Per-slice transformations** — independent probabilities for reverse,
   stutter-repeat, and shuffle that apply per chunk rather than globally.
6. **Anti-click crossfade envelopes** at slice boundaries.
7. **Real-time FX preview** with a separate distortion → ring-mod → delay →
   phaser chain that can be auditioned before committing to file.
8. **Local-only processing** — everything runs on the user's machine; nothing
   uploaded anywhere.

The rest of this document explains each of those in detail.

---

## 1. What is slurmcore? (Background for newcomers)

If you've spent time on TikTok or YouTube Shorts in the past few years, you've
almost certainly heard a slurmcore edit even if you didn't know the name. The
sound is unmistakable:

- A familiar pop, rock, or hip-hop song you'd recognize in a second normally
- ...sped up to a sprint pace (often 1.5× to 3× the original)
- ...with the pitch noticeably higher (vocals sound chipmunk-adjacent)
- ...and chopped into rapid-fire fragments that stutter, restart, and
  fragment what would otherwise be a continuous melodic line

The aesthetic descends from a few traditions:

- **Vaporwave / future funk** — the late-2010s genre that slowed down or
  sped up corporate funk and 80s pop, treating familiar songs as raw material
  for transformation
- **Footwork and juke** — Chicago dance music genres built around extreme
  repetition and fragmenting vocal samples into stuttering loops
- **Stutter-edit and beat-repeat plugins** — production tools developed in
  the 2000s (notably iZotope's Stutter Edit) that automated chopping and
  rearranging short audio segments
- **Mashup culture** — the broader mid-2000s practice of treating finished
  songs as a deck of cards to be shuffled and re-dealt

What makes "slurmcore" distinct from these older traditions is mostly its
*delivery medium* and *production speed*. Where vaporwave producers might
spend hours crafting an edit, slurmcore producers often work fast — sometimes
in browser-based tools, sometimes in a single take — and post directly to
short-form video platforms where the algorithm rewards the immediate
pattern-recognition payoff of "wait, is that... [familiar song]?".

There's no canonical slurmcore "DAW" or "plugin" — the genre is defined by
the *result*, not the *tools*. Producers reach for whatever's fastest:
Audacity for its free price tag and built-in time-stretch, TikTok's own
sped-up filter, web tools like vocaloid.club's tempo changer, or full DAWs
with beat-repeat plugins.

> **For newcomers:** Think of slurmcore as the audio equivalent of a YouTube
> Poop video. You take a known thing, fragment it past the point of being
> functional-as-music in the original sense, and the *broken-ness itself*
> becomes the aesthetic point. The listener's ear keeps trying to reassemble
> the original, and the resulting tension between "I know this song" and
> "this is not how it goes" is the hook.

---

## 2. The traditional slurmcore workflow

Most slurmcore tracks are produced via some combination of these steps,
roughly in order:

### 2.1 Source selection

The producer picks a song that's instantly recognizable — usually something
with strong melodic identity (a hook, a chorus, a famous vocal line) since
the slurm transformation will fragment everything but the listener still
needs to identify the source within the first few seconds.

### 2.2 Speed-up

The track is sped up. In simple tools (TikTok filters, Audacity's "Change
Speed" effect, basic web converters), this is done via **resampling** —
playback rate is increased and the audio's pitch goes up proportionally as
a side effect. A 2× speed-up shifts the pitch up by an octave. This is the
classic "chipmunk" sound.

In more advanced workflows, the producer might use **time-stretching**
(via SoundTouch, Élastique, Rubber Band, or a DAW's built-in algorithm) to
preserve pitch while changing tempo. This requires the tool to do something
fancier than just play the samples back faster — typically phase-vocoder or
overlap-add techniques that resynthesize the audio at the new tempo.

### 2.3 Chopping

The sped-up audio is sliced into short segments. In a DAW workflow, this
is usually done by hand: the producer scrubs through the timeline, eyeballs
the waveform for transients, and sets cut points by ear. In simpler tools,
beat-repeat plugins do this automatically by triggering loop-starts on a
fixed grid.

### 2.4 Stutter, repeat, reverse

Some chops get repeated (stuttered), some get reversed, some get rearranged.
The proportion and pattern is again usually placed by ear or with a step
sequencer. The "feel" is hand-tuned.

### 2.5 Reassembly + bounce

The chopped, stuttered chunks are concatenated back into a continuous
playback timeline and exported as an MP3 or WAV. Often there's a final
limiter or compressor pass to keep the level consistent across chunks of
varying loudness.

### 2.6 Optional FX

Some producers add post-effects: bit-crushing, lo-fi tape wow, granular
reverb, sidechain pumping. These are taste decisions, not load-bearing
to the genre.

---

## 3. Where Slurmify diverges

This is where the comparison gets interesting. Slurmify automates the same
broad workflow but makes deliberate choices at each stage that produce
different results — sometimes cleaner, sometimes more chaotic, always
reproducible.

### 3.1 Pitch and tempo are independent controls

> **Newcomer view:** In most slurmcore tools, "speed up" and "make higher
> pitch" are the same knob. Slurmify gives you two separate sliders so you
> can speed up *without* sounding like a chipmunk, or pitch up *without*
> changing the tempo, or both independently.

> **Expert view:** Slurmify uses [Rubber Band Library](https://breakfastquay.com/rubberband/)
> via `pyrubberband` for both time-stretching and pitch-shifting. The
> pipeline applies time-stretch first (preserving pitch) at the user-set
> `speed` multiplier, then optionally a pitch-shift in semitones (preserving
> the new tempo) as a separate stage. The "preserve pitch when speeding up"
> checkbox toggles between this independent mode and a cheap
> `np.interp`-based resample that couples pitch and tempo (the classic
> chipmunk effect, kept as an option because it's part of the slurmcore
> aesthetic). Two independent Rubber Band passes are quality-expensive but
> avoid the artifacts of trying to do both transforms in a single phase
> vocoder pass.

The user can therefore land anywhere in the 2D space of `(tempo × pitch)`
that traditional slurmcore tools collapse to a 1D resample line. Want a
song at half speed but the original pitch? Possible. Want it at original
tempo but pitched up an octave? Possible. Want chipmunk mode? Just
uncheck "preserve pitch."

### 3.2 Beat-grid-aware slicing

> **Newcomer view:** Most slurmcore producers chop by ear and eye —
> watching the waveform and clicking. Slurmify listens to the song, figures
> out the tempo, and places chops on a musical grid (every quarter note,
> every sixteenth note, etc.). You pick the resolution; the math figures
> out where the cuts go.

> **Expert view:** `librosa.beat.beat_track` is called on the time-stretched
> audio to estimate BPM. The chosen slice resolution maps to a "subdivisions
> per beat" multiplier via a `res_map` lookup (`1/4`→1, `1/8`→2, `1/16`→4,
> ..., `1/128`→32, plus the reverse direction `1/2`→0.5 and `1/1`→0.25 for
> slices that span multiple beats). The grid spacing in samples is then
> `int(sr * 60 / bpm / subdivs)` with a 256-sample floor (~6 ms at 44.1 kHz)
> to prevent unstable micro-slices.

Why this matters: hand-placed chops drift. They fall *near* musical events
but not *on* them. Listeners' ears reach for a regular pulse and don't find
one, which is sometimes what you want and sometimes just sloppy. Beat-grid
slicing produces a defined rhythmic feel even when the chops are short or
the source is dense.

### 3.3 Transient-aware hybrid slicing

> **Newcomer view:** Real songs have moments where something musical
> happens — a kick drum, a snare, the start of a syllable. Slurmify can
> detect these moments and snap chops to land *on* them rather than near
> them. A slider lets you choose how much you trust the grid versus how
> much you trust the song's actual events.

> **Expert view:** When `transient_sensitivity > 0`, `librosa.onset.onset_detect`
> runs on the audio with a `delta` threshold inversely proportional to
> sensitivity. Detected onset frames are converted to sample indices. For
> each grid point, the algorithm searches a window around it (window width
> proportional to `1 - sensitivity`) for a nearby onset and snaps to the
> closest one if found. At `transient_sensitivity = 1.0`, the grid is
> bypassed entirely and slice points are pure-onset. At `0.0` it's
> pure-grid. In between, you get a hybrid that's mostly grid but bends to
> follow musical events when they're nearby.

This is the slurmify equivalent of a "slice to MIDI" feature in Ableton or
similar DAWs, but exposed as a continuous knob rather than a binary mode.
The sensitivity slider lets the user balance "I want it to feel rhythmic
and predictable" against "I want it to follow what the song is actually
doing."

### 3.4 MAX RANDOM mode (trimodal distribution)

> **Newcomer view:** A special mode that throws out the grid entirely and
> chops at random durations — but not just random in a boring way. Each
> chop independently picks one of three categories: a *stutter* (very short,
> 5–30 ms — sounds like a glitch), a *chop* (medium, 100–500 ms — recognizable
> chunk of audio), or a *held passage* (long, 1–4 seconds — almost plays
> through normally). Consecutive chops can be wildly different sizes, so
> you hear a tiny stutter next to a long held vowel next to a regular chop.
> No human would chop a song like this; it's a kind of chaos that sounds
> intentional precisely because it's so categorically random.

> **Expert view:** When `resolution == "MAX RANDOM"`, the BPM-grid pipeline
> is bypassed. A while-loop walks the audio sample-by-sample, drawing each
> slice's duration via:
>
> ```python
> name, lo_ms, hi_ms = random.choice([
>     ("stutter", 5.0,    30.0),
>     ("chop",    100.0,  500.0),
>     ("held",    1000.0, 4000.0),
> ])
> dur_ms = 10.0 ** random.uniform(np.log10(lo_ms), np.log10(hi_ms))
> ```
>
> The discrete bucket choice (1/3 each via `random.choice`) explicitly
> *skips* the 30–100 ms and 500–1000 ms ranges that would otherwise
> dominate a continuous log-uniform distribution and blend into a uniform
> chop-tempo texture. Within each bucket, the duration is log-uniform
> (equal probability per decade), preserving meaningful variation. All RNG
> goes through Python's `random` module, which the slurmify entrypoint
> seeds from the user-provided seed, so the same seed reproduces the
> same chaos sequence exactly. When MAX RANDOM is selected, the
> `randomize slice order` checkbox auto-enables (the chaos is most
> apparent when slices are also shuffled, not played in source order).

This is something you genuinely couldn't do in a typical DAW without
either writing a script or spending hours hand-placing chops. It's also
deliberately pushed past the "musical" boundary — the 5 ms stutter slices
are at audio-rate (you hear them as a buzz, not as discrete events), and
the 4-second held chunks are long enough that the slurm starts to feel
like it forgot to slurm. The juxtaposition is the point.

### 3.5 Per-slice transformations

> **Newcomer view:** Three sliders set the *chance* per slice that
> something happens to it:
> - **Reverse chance**: probability each slice plays backwards
> - **Stutter chance**: probability each slice is stuttered
> - **Skip length (ms)**: how much of each slice is used as the looping head
>   when stutter fires — 0 = full slice (classic), >0 = stutter-edit skip mode
> - **Reps (max)**: upper bound for the random repeat count (draw is 2 → max)
> - **Spread**: how much the skip length varies per-stutter-event (0 = fixed,
>   1 = each stutter independently picks a random head length up to skip_ms)
> - **Randomize order**: toggle for whether slices play in source order or shuffled
>
> So at `reverse_chance = 0.3`, roughly 30% of your chunks will play in
> reverse. You don't pick which ones; the dice roll for each.

> **Expert view:** The per-slice loop in `slurmify()` does:
>
> ```python
> for s in slices:
>     s = apply_envelope(s, sr, envelope_ms)
>     if reverse_chance > 0 and random.random() < reverse_chance:
>         s = s[::-1].copy()
>     if stutter_chance > 0 and random.random() < stutter_chance:
>         actual_reps = random.randint(2, max(2, stutter_max_reps))
>         if stutter_skip_ms > 0:
>             # Skip mode: loop only the head of the slice.
>             if stutter_spread > 0:
>                 lo_ms = max(5.0, stutter_skip_ms * (1.0 - stutter_spread))
>                 eff_ms = random.uniform(lo_ms, stutter_skip_ms)
>             else:
>                 eff_ms = stutter_skip_ms
>             head_n = max(int(sr * 0.005), int(sr * eff_ms / 1000.0))
>             head = apply_envelope(s[:head_n], sr, envelope_ms)
>             s = np.tile(head, actual_reps)
>         else:
>             # Classic: tile the full slice.
>             s = np.tile(s, actual_reps)
>     processed.append(s)
> if randomize_order:
>     random.shuffle(processed)
> out = np.concatenate(processed)
> ```
>
> In classic mode (`stutter_skip_ms = 0`), stutter tiles the full slice 2→max_reps
> times — you hear the complete phrase repeated. In skip mode, the loop head is
> `eff_ms` milliseconds (default: `stutter_skip_ms`, optionally spread-randomised
> per-event). Only the head is tiled, so the output sounds like a stuck CD or
> vinyl needle rather than a phrase repeat. The `apply_envelope()` call on the
> head suppresses the click at each repeat boundary. All decisions are seeded
> for reproducibility.

The architectural choice here is *probabilistic* rather than *patterned*.
There's no step sequencer telling you "reverse on slice 3, stutter on
slice 7." Instead, every slice independently rolls dice. The `stutter_spread`
parameter extends this further: even the skip length itself becomes a
per-event random variable, so the texture within a single render contains
a mix of micro-blips, medium skips, and near-phrase repeats — all seeded
and reproducible.

This maps conceptually to Ableton's Beat Repeat (Grid = slice size,
repeat count = reps) and iZotope's Stutter Edit (buffer capture size =
skip_ms, repetitions = reps), but expressed as per-slice probability with
variance, rather than a triggered real-time effect.

### 3.6 Anti-click crossfade envelopes

> **Newcomer view:** When you cut audio into pieces and stick them back
> together, each cut point can produce an audible "click" — the waveform
> jumps suddenly from one value to another. Slurmify applies a tiny
> fade-in and fade-out at each slice boundary so the cuts are smooth.
> A slider controls how long the fade is (0 ms = hard cuts, classic
> clicky aesthetic; higher = smoother).

> **Expert view:** `apply_envelope()` applies linear fade-in and fade-out
> ramps of `n_fade = min(int(sr * envelope_ms / 1000), len(slice) // 2)`
> samples to each slice. At `envelope_ms = 0` the function returns the
> slice unchanged (true hard cut, with all the spectral content of the
> discontinuity). At `envelope_ms = 2` (default), fades are 88 samples
> at 44.1 kHz — short enough to be sub-perceptual at most slice lengths
> but long enough to suppress most boundary clicks. For very short
> slices (sub-10 ms in MAX RANDOM stutter mode), the fade can dominate
> the slice (so the slice is *mostly* envelope), which is a known and
> intentional limitation — at audio-rate slicing, you're already in
> click-textured territory aesthetically.

Most hand-chopped slurmcore tracks have noticeable clicks at slice
boundaries because the producer either didn't notice them or accepted
them as part of the lo-fi texture. Slurmify gives you the choice
explicitly: 0 for clicky-classic, anything higher for smooth.

### 3.7 Real-time FX preview pedalboard

> **Newcomer view:** After your slurm is rendered, an "FX preview" panel
> opens up with sliders for distortion, ring modulator, delay, and phaser.
> You play the slurm output and twist the sliders — changes are instant,
> no re-rendering. When you find a sound you like, click "burn FX to
> file" to bake those settings into a new audio file. This is closer to
> how a guitar pedal-board works than how DAW plugins work.

> **Expert view:** The FX preview chain runs in the browser via Web Audio
> API: the Python output's audio file is bound (once, exactly once — see
> ADR notes about `createMediaElementSource` being single-use per element)
> to a chain of `WaveShaperNode` (distortion), `GainNode` controlled by
> a sine `OscillatorNode` (ring modulation), `DelayNode` with feedback
> loop (delay), and a 4-stage `BiquadFilterNode` allpass cascade with LFO
> (phaser). Slider changes update the corresponding `AudioParam` values
> in real time with no re-render. The "burn" path runs the same DSP in
> Python NumPy/SciPy and bounces to a new file, so what you preview is
> what you bake.

This is meaningfully different from the typical slurmcore workflow where
post-FX requires a separate rendering pass through a DAW or external
tool — the immediate audition lets you tune by ear in a way that's
otherwise tedious.

### 3.8 Reproducible chaos via seed

> **Newcomer view:** There's a "seed" textbox. Leave it blank and every
> slurm is different (the dice are fresh each time). Type a number in
> and the same settings + same seed always produce the exact same slurm.
> Useful when you've made something cool and want to bring it back later,
> or when you want to A/B compare two different setting tweaks against
> the same underlying randomness.

> **Expert view:** When `seed` is provided, `slurmify()` calls both
> `random.seed(seed)` and `np.random.seed(seed)` at the top of processing.
> Every probabilistic decision downstream — slice point selection in MAX
> RANDOM, reverse and stutter dice rolls, shuffle order, RNG-derived
> filename jumble — flows from these seeded generators. Identical
> `(input file, settings, seed)` triples produce bit-identical output
> files. This is the property a typical slurmcore workflow lacks
> entirely; once you've bounced a chop, you can't recreate it without
> the project file.

The seed property also enables *self-describing* output files: every
rendered MP4 carries a JSON metadata blob in its description atoms
listing every parameter including the seed, so any rendered slurm video
contains everything needed to reproduce itself.

### 3.9 Local-first, no cloud

> **Newcomer view:** Everything runs on your computer. Your audio
> doesn't get uploaded anywhere. The app opens a local web page in your
> browser (the URL starts with `127.0.0.1`, which is your own machine)
> and that's where the UI lives, but no data leaves the box.

> **Expert view:** The app is a self-contained Python process running
> a Gradio server bound to `127.0.0.1`. There's no telemetry, no
> third-party API calls, no cloud DSP. Time-stretching uses the bundled
> `rubberband` binary, audio I/O via `librosa` + `soundfile`, MP3
> encoding via the bundled `ffmpeg`. The PyInstaller bundle includes
> all dependencies; the app runs offline indefinitely. Output files
> live in a per-session subdirectory of the system temp dir and are
> wiped on quit (with orphan cleanup on next launch covering crashed
> sessions).

For producers using slurmcore on copyrighted source material — which is,
honestly, most of them — the privacy story matters. Web-based slurm tools
necessarily upload your source to a remote server; Slurmify never does.

---

## 4. Signal flow diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  INPUT FILE  (any audio or video container — mp3, wav, mp4, mkv...) │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  load_audio()                     │  librosa.load (audioread/ffmpeg
                │  → mono float32 @ 44.1 kHz        │   handles video container demux
                └─────────────────┬─────────────────┘   transparently)
                                  │
                ┌─────────────────▼─────────────────┐
                │  In/Out trim                       │  start_sec, end_sec slicing
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  Time-stretch (preserve_pitch=ON) │  pyrubberband.time_stretch
                │  OR resample (preserve_pitch=OFF) │  OR np.interp resample
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  Pitch shift (semitones)          │  pyrubberband.pitch_shift
                │  Skipped if zero                  │  (independent of speed)
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  detect_slice_points()            │
                │                                   │
                │  IF resolution == "MAX RANDOM":   │
                │    Trimodal: stutter/chop/held    │
                │    while pos < len(y):            │
                │      bucket = choice(3)           │
                │      dur = log_uniform(bucket)    │
                │      pos += samples(dur)          │
                │      append(pos)                  │
                │                                   │
                │  ELSE (grid mode):                │
                │    bpm = librosa.beat.beat_track  │
                │    grid = arange(0, len, samples_ │
                │           per_subdiv)             │
                │    IF transient_sens > 0:         │
                │      onsets = librosa.onset_      │
                │               detect              │
                │      snap each grid point to      │
                │        nearest onset (window      │
                │        ∝ (1-sensitivity))         │
                │    return grid_points             │
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  Per-slice loop:                  │
                │    s = apply_envelope(s, env_ms)  │  fade-in/out, anti-click
                │    if rand() < reverse_chance:    │
                │      s = s[::-1]                  │  reverse this slice
                │    if rand() < stutter_chance:    │
                │      s = tile(s, choice(2,2,3,4)) │  repeat this slice
                │    processed.append(s)            │
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  if randomize_order:              │  global shuffle
                │    shuffle(processed)             │
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  out = concatenate(processed)     │
                │  Soft-normalize peak to -1 dBFS   │
                └─────────────────┬─────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  _write_audio()                   │  wav/flac/ogg/aiff direct via
                │  → output file in session tmpdir  │   soundfile; mp3/aac via ffmpeg
                └─────────────────┬─────────────────┘
                                  │
                                  ▼
                       ┌─────────────────┐
                       │  audio_out      │  rendered into Gradio UI
                       └────────┬────────┘
                                │
                                ├──────► Real-time FX preview (Web Audio,
                                │         distortion → ring → delay → phaser)
                                │         ─ live, no re-render
                                │
                                ├──────► Burn FX to file (Python NumPy
                                │         re-runs the same DSP, bakes to
                                │         a new audio file)
                                │
                                └──────► YouTube MP4 export (audio +
                                          looping animation → ffmpeg
                                          stream-copy + AAC encode)
```

---

## 5. Detailed comparison table

The table below condenses every dimension where Slurmify and "general
slurmcore practice" diverge. "General slurmcore" here describes the
typical mid-skill producer's workflow in a DAW like Ableton or FL Studio,
not the specific exception cases where a producer happens to use a more
sophisticated tool.

| Dimension | General slurmcore practice | Slurmify |
|---|---|---|
| **Speed and pitch coupling** | Usually coupled (resample). "Faster = higher-pitched" is the default. | Independent by default (Rubber Band time-stretch + separate pitch-shift). Coupled is opt-in via "preserve pitch" toggle. |
| **Time-stretch quality** | DAW-default. Usually phase vocoder, sometimes Élastique or SoundTouch. | Rubber Band Library — high-quality phase-vocoder with formant preservation options. |
| **Slice placement** | Hand-placed, by ear, scrubbing the waveform. | Algorithmic: BPM-detected grid, optionally snapped to onsets. Reproducible. |
| **Slice resolution control** | Implicit, varies with hand-chopping. | Explicit: 9 options (1/1, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64, 1/128, MAX RANDOM). |
| **Transient awareness** | None — chops fall where the producer clicks. | `transient_sensitivity` slider hybrids grid-based and onset-detected slice points. |
| **Random slice mode** | Not standard. Sometimes producers manually create chaos. | MAX RANDOM with trimodal distribution: stutter / chop / held buckets, each log-uniform within. |
| **Reproducibility** | Project file required. Without it, the chops are gone. | Seed parameter. Same input + settings + seed = bit-identical output. |
| **Stutter pattern** | Step-sequencer-driven or hand-placed. Patterns repeat. | Per-slice probability. Each slice independently rolls dice. No fixed pattern. Skip mode (skip_ms > 0) produces the CD-skip / stutter-edit head-loop sound. |
| **Reverse pattern** | Manually applied per slice. | Per-slice probability via `reverse_chance` slider. |
| **Slice envelope** | Usually nonexistent. Hard cuts produce clicks that are accepted as lo-fi texture. | Adjustable crossfade per slice (0 ms = hard cut classic, higher = smooth). |
| **Boundary clicks** | Common, often intentional. | Suppressed by default at 2 ms envelope. |
| **Output normalization** | Manual via DAW limiter or compressor. | Automatic peak-normalize to -1 dBFS. |
| **FX chain** | DAW plugins, separate from chopping. Re-rendering required for changes. | Real-time Web Audio preview (distortion → ring → delay → phaser), audition-then-bake. |
| **Input formats** | Whatever the DAW supports. Often audio-only. | Any audio or video container — extracted via librosa+ffmpeg transparently. |
| **Output formats** | DAW export: WAV, MP3, OGG, etc. | WAV, FLAC, OGG, AIFF (direct via soundfile); MP3, AAC (via bundled ffmpeg). Plus YouTube-ready 1080p MP4 with branded animation loop. |
| **File hygiene** | Files live wherever the DAW puts them; manual cleanup. | Per-session tempdir, auto-wiped on quit, orphan-swept on next launch. |
| **Privacy** | Depends on tool. Web-based slurm tools upload your source. | 100% local. Server bound to 127.0.0.1. No telemetry. |
| **Tool footprint** | Whatever DAW (often $$$, large install). | Single Python file (~3000 lines) or signed/notarized macOS .app bundle. |
| **Reproducible workflow** | Hand-tuned, hard to replicate. | Every parameter exposed, seed-deterministic, self-describing output metadata. |
| **Ease of getting started** | Moderate — DAW learning curve. | Low — drop file, twist knobs, click slurmify. |
| **Ceiling for expressivity** | Very high — full DAW power. | Moderate — opinionated about workflow. Adds FX accordion, video export. |

---

## 6. Why these choices matter

### The neophyte angle

If you've never made a slurm before and you sit down with a typical DAW
to try, you'll spend 30+ minutes just figuring out where to put the
chop markers, then realize you need to do it again with different
spacing, then realize you can't easily try "what if it was 2× faster
without sounding like a chipmunk," then give up and use Audacity's
"Change Speed" which sounds like a chipmunk. Slurmify replaces all of
that with a knob-twisting workflow: load audio, set speed, set
resolution, click slurmify, listen. If you don't like it, change a
knob and click slurmify again. It's a way to *explore* the slurm space
without needing DAW expertise.

### The expert angle

If you're already a producer who knows your way around chopping, what
Slurmify gives you is **reproducibility** and **transient awareness as a
continuous control**. You can't easily seed a chop session in a DAW —
once you've placed the cuts, that's it; you can't easily recover the
"random" choices. With Slurmify, your seed + settings + source = exact
output, every time. And the `transient_sensitivity` knob lets you
continuously vary the placement bias without re-chopping.

The MAX RANDOM trimodal distribution is also genuinely hard to replicate
in a DAW. Drawing from three log-uniform buckets with equal categorical
probability isn't a thing any DAW exposes; you'd write a script. Here
it's a radio button.

### The aesthetic angle

The choices in Slurmify push the slurmcore aesthetic in specific
directions. The trimodal distribution, in particular, is
**categorically random** rather than continuously random — the listener
hears stutter bursts, then long held passages, then chops, then more
stutter bursts. This is a different sound than the smooth-random
log-uniform that produces mostly mid-tempo chops with occasional
outliers. Whether "categorical chaos" is *better* than "continuous
chaos" is taste, but they're audibly different.

The auto-shuffle on MAX RANDOM is a similar opinionated choice — you
*could* keep slices in source order (and Slurmify lets you), but the
auto-on default reflects the project's view that "MAX RANDOM" should
sound maximally random by default, not be a setting that requires you
to turn on a second checkbox to actually feel random.

---

## 7. What Slurmify is NOT

Worth being clear about the boundaries:

- **Not a full DAW.** No multi-track mixing, no MIDI, no plugins beyond
  the four built-in FX. If you want to do sound design or composition,
  use Ableton or Reaper. Slurmify slurms a single audio source.
- **Not a music transcription tool.** It estimates BPM but doesn't
  detect chords, doesn't extract stems, doesn't recognize melodies.
- **Not a stem separator.** If you give it a full mix, it slurms the
  full mix. If you want to slurm just the vocals, separate them first
  with something like Demucs.
- **Not real-time.** The slurmify pipeline is non-realtime — you click
  a button, you wait a few seconds (depending on file length), you get
  output. The FX chain *is* real-time, but only as preview after the
  initial slurm is rendered.
- **Not a TikTok-style auto-edit.** It doesn't pick "the best part" of
  your song. You give it audio, it slurms what you give it. Use the
  in/out trim controls to isolate a section first.

---

## 8. Glossary

A reference for terms used above.

| Term | Definition |
|---|---|
| **Slurmcore** | An informal microgenre / production technique characterized by aggressive speed-up, pitch-shift, and chopping of recognizable source music, typically posted to short-form video platforms. |
| **Slurmify** | The Subvoyant SIENA Slurmer application — a Python tool implementing the slurmcore method with the specific opinionated choices documented here. Also a verb: "to slurmify a track." |
| **Chop / slice** | A short audio fragment cut from the source, treated as a unit for rearranging, repeating, or reversing. |
| **Resampling** | Changing playback rate by reading samples faster or slower. Couples pitch and tempo (faster = higher pitch). The "chipmunk" effect. |
| **Time-stretching** | Changing tempo while preserving pitch, via algorithms like phase vocoder, SOLA, or Rubber Band. Higher quality than resampling, more CPU. |
| **Pitch-shifting** | Changing pitch while preserving tempo. Inverse problem of time-stretching, often using the same algorithm class. |
| **BPM** | Beats per minute. The tempo of a track, e.g. 120 BPM = 2 beats per second. |
| **Onset / transient** | A moment of significant energy increase in audio — usually a percussion hit, a syllable start, or a chord change. Detectable via spectral flux or similar. |
| **Slice resolution** | How finely the audio is chopped relative to the beat. 1/4 = quarter notes (one chop per beat at 4/4), 1/16 = sixteenth notes, etc. |
| **Subdivision** | A division of the beat. 1/16 means 4 subdivisions per beat. |
| **Crossfade envelope** | A short fade-in and fade-out applied to each slice's edges to suppress click artifacts at slice boundaries. |
| **Stutter** | Repeating a slice 2–4 times in immediate succession. |
| **Reverse** | Playing a slice's samples backwards. |
| **Shuffle / randomize order** | Concatenating slices in random order rather than source order. |
| **Seed** | An integer that initializes a random number generator. Same seed + same code = same "random" output. Provides reproducibility. |
| **Log-uniform distribution** | A probability distribution where the *logarithm* of the value is uniformly distributed. Equal probability per decade — a value between 5 and 50 is as likely as a value between 500 and 5000. |
| **Trimodal distribution** | A distribution with three peaks. Slurmify's MAX RANDOM uses three discrete buckets (stutter / chop / held), each log-uniform within. |
| **DSP** | Digital Signal Processing. The math that runs on audio samples. |
| **Phase vocoder** | A time-frequency analysis-resynthesis technique used for high-quality time-stretching and pitch-shifting. |
| **Rubber Band Library** | A specific high-quality phase-vocoder implementation by Breakfast Quay (GPL-licensed). Used by Slurmify via the `pyrubberband` Python wrapper. |
| **librosa** | A Python library for music and audio analysis. Used by Slurmify for loading, BPM detection, and onset detection. |
| **Web Audio API** | A browser API for real-time audio processing. Used by Slurmify for the live FX preview chain. |
| **Anti-click** | Of an envelope or fade: short enough to be inaudible as a fade but long enough to suppress the click that would result from a sample-level discontinuity. |
| **Hard cut** | A slice boundary with no fade. Produces an audible click at the discontinuity, which can be a deliberate aesthetic choice. |

---

## 9. Further reading

If you want to go deeper on the techniques referenced above:

- **Time-stretching algorithms** — see Roads, *Microsound* (2001), and the
  Rubber Band Library documentation for details on phase-vocoder and
  granular approaches.
- **Onset detection** — Bello et al., *A Tutorial on Onset Detection in
  Music Signals* (IEEE TSAP, 2005), covers the algorithm family librosa
  uses.
- **Beat tracking** — Ellis, *Beat Tracking by Dynamic Programming*
  (Journal of New Music Research, 2007), is the algorithmic basis for
  `librosa.beat.beat_track`.
- **The general slurmcore aesthetic** — search YouTube and TikTok for
  "sped up," "stutter edit," and "slurm." There's no canonical text;
  the genre exists in practice rather than theory.

For Slurmify's own implementation, see `TECHNICAL.md` for the engineering
narrative and `docs/adr/` for the architecture decision records.

---

*Subvoyant SIENA Slurmer · v0.1.6 · Local, reproducible, opinionated slurmcore.*
