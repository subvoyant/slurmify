# The Quiet Revolution Inside a Dancing Cat

## How Subvoyant's SIENA Slurmer turns any audio file into something that sounds like a memory of itself — and why a single Python module called `slurmcore` is the whole argument

---

You drop the vocal take onto a small grey rectangle. A pixelated cat starts dancing in the corner of the window. About three seconds later the cat stops, and out the other side comes something that is, technically, the file you uploaded — and is, on every other axis, not.

Words you said in one breath have been rearranged into a different breath. Some of the syllables are reversed. Two of them stutter, briefly, like the singer is having a thought mid-word. A long phrase that ran for four seconds in the original now hangs in the air for six, slightly more dilated than memory. The pitch is identical. The clock is broken.

This is **SIENA Slurmer**, the desktop application from a small studio called **Subvoyant**, and the experience of using it for the first time is faintly unsettling in the way that only good tools are. The tool is asking you a question — *what does your audio sound like if it doesn't have to make sense in time?* — and unlike most software, it does not particularly care which answer you pick.

Under the hood, Slurmer is doing something that has a name. It is doing **granular synthesis**, with a few opinionated twists, and it is doing it in roughly two thousand lines of Python in a file called `slurmcore.py`. That file, more than the dancing cat or the four switchable skins or the tiny easter-egg GIFs that pop out from behind buttons when you hover, is the thing worth talking about.

> ### **The five-year-old version**
>
> Imagine you have a tape of someone reading a story.
>
> You cut the tape into a pile of pieces. Some pieces are tiny — too small to hear a word. Some are bigger — about one syllable. Some are big — a whole sentence. Then you glue the pieces back together in a different order. Sometimes you play a piece backwards. Sometimes you play the same piece three times in a row really fast.
>
> When you press play, it sounds like the same person reading the same story, except the story isn't there anymore. Just the voice, doing something else.
>
> That's what slurmify does. The computer does the cutting and gluing.

---

## I. What it actually is

Slurmify, in plain English, is a Mac desktop application that takes audio files and produces other audio files. You can give it almost anything — MP3, WAV, FLAC, AIFF, OGG, OPUS, M4A, AAC, WMA, or ALAC — or, for that matter, you can give it a video file (MP4, MOV, MKV, WebM, MPEG, 3GP, and a handful more), and it will pull the audio track out and use that. Output is whatever you ask for: WAV, FLAC, OGG, AIFF, MP3, AAC.

In between, you turn knobs. There are roughly twenty of them, organized into a few rows. The most consequential is a radio dial labelled **resolution**, which determines how the audio gets carved up. Choices are musical fractions: 1/1, 1/2, 1/4, 1/8, 1/16, all the way down to 1/128, which is granular enough to feel like the buzz of a fluorescent light. There is one further setting, presented as a separate option on the same dial, called `MAX RANDOM`. We will return to it.

There are four time-related sliders next to the resolution dial — stutter skip, beat trim start, beat trim end, beat gap — each of which can be expressed in milliseconds (the prosaic option) or in musical note values (1/8, 1/16T, 1/4·, and so on, including dots for dotted notes and T for triplets). Each slider has a tiny chip that toggles between **ms** and **♪**. You pick the unit you find easier to think in. It is the kind of detail that takes a quarter-hour to add and changes the lived experience of using the app.

There are four "skins" — visual modes — switchable from a dropdown in the corner: **default** (cyan and charcoal), **acid cathedral** (mint and hot pink, brutally psychedelic), **hardware rack** (LED amber on monospace black, like an old guitar pedal), and a fourth in development. Switching skins is, on the engineering level, a CSS attribute change — a single `data-skin` value flipping on the body element — and on the experience level a wholesale change of mood.

And there is a dancing cat. Her name is Siena. She has her own GIF. She runs while the audio is being processed and stops when it's done. You cannot save her image to your computer; the right-click context menu is suppressed. She is not, the codebase notes carefully, a downloadable asset.

---

## II. Granular synthesis: a sixty-eight-year argument

Chopping audio into tiny pieces and gluing them back together is not new. The technique has a name and a lineage, and the lineage is unusually well-documented for a corner of music technology.

In **1958**, the Greek-French composer **Iannis Xenakis** released a piece for the Brussels World's Fair called *Concret PH*. It was four minutes long. To make it, he physically spliced magnetic tape into thousands of fragments, each containing a tiny burst of recorded sound (in this case, the noise of burning coal), and reassembled them into a billowing cloud of micro-events. He did not call this **granular synthesis** — that term was coined later, in the 1970s — but he had defined the technique. *Concret PH* is the first piece of music in the lineage Slurmify belongs to.

In **1974**, the American composer **Curtis Roads** wrote the first computer implementation of granular synthesis. He spent the following four decades writing about it, eventually publishing the encyclopedic *Microsound* in 2001. *Microsound* is one of the things you read if you want to write software like Slurmify. It traces the technique back to the physicist **Dennis Gabor**, who proposed in the 1940s that any sound could be decomposed into tiny "acoustic quanta." This is, formally, the seed.

In **1991**, in Berlin, three musicians under the name **Oval** — eventually solo project of **Markus Popp** — began damaging the surfaces of compact discs with X-Acto knives, paint, and tape. The CDs would skip when played, producing brief, glitchy artifacts. Popp would record those artifacts and reassemble them into music. *Systemisch* (1994) and *94diskont.* (1995) are the canonical documents. Björk would later sample one of the tracks on her 2001 album *Vespertine*. Oval is the populist hinge in the lineage — the moment granular synthesis stopped being only an academic technique and became a *sound*.

Slurmify is a member of this lineage, but with a populist bent of its own. It does not require splicing tape, or writing C++, or sandpapering compact discs. It ships as a single 110-megabyte DMG. You drag the dancing-cat-icon to your Applications folder. You double-click. The whole tradition is now operable from a MacBook trackpad.

---

## III. Inside `slurmcore.py`

If you open the slurmify codebase — the project is open-source, GPL-3 — you will find a flat directory of about two dozen files. The one that matters is `slurmcore.py`, and it has a particular character. It is roughly two thousand lines long, and the first hundred of those lines are a comment.

The comment is a manifesto. It explains, with the patience of someone who has been bitten before, what the file is allowed to import (numpy, librosa, scipy, pyrubberband) and what it is not (anything that touches the file system, the operating system, or the user interface). The rule is monastic: numpy arrays in, numpy arrays out. Nothing else.

This sounds dogmatic until you've spent an afternoon trying to debug an audio routine that's also writing files to disk and printing things to a UI. The discipline pays for itself within a week.

The pipeline inside `slurmcore` is, in order:

1. **Load** the audio (handled in a sister module, `slurmio.py`, which is the only place file paths exist) at a fixed sample rate of 44,100 Hz — CD quality, the canonical resolution of glitchable audio since 1982.
2. **Detect slice points** — figure out where to cut. This blends two strategies. *Beat-grid slicing* asks **librosa** (the canonical Python audio-analysis library) to estimate the BPM and find beat positions, then subdivides those positions according to the user's chosen resolution. *Transient snapping* asks librosa for the moments where new notes or drum hits begin, and pulls grid points toward them. A slider lets the user blend between the two — pure grid, pure transient, or hybrid.
3. **Stretch** the audio (optionally) using the **Rubber Band Library**, written by **Chris Cannam** at Breakfast Quay in England. Rubber Band is fifteen years old, GPL-licensed, used in Audacity, in Mixxx, and now in Slurmify. It is the part of the pipeline that lets you change tempo without changing pitch, or vice versa. (Slurmify's bundled build also ships the binary; an early v0.2 release accidentally forgot it, and the consequences were colourful.)
4. **Slice** the audio at the points found in step 2.
5. **Mutate** each slice. Some slices may be reversed (with a probability the user controls). Some may stutter — repeated 2 to 8 times in rapid succession. Some sequences are shuffled.
6. **Envelope** every slice with a tiny fade-in and fade-out — about 5 milliseconds at 44.1 kHz. This is anti-click hygiene. Without it, the boundaries between slices produce audible pops.
7. **Concatenate** the slices.
8. **Normalize** the resulting waveform so it doesn't clip.

A second, optional stage runs the result through an FX chain: **distortion** (a tanh waveshaper), **ring modulator** (multiplying the signal against a sine wave at a tunable frequency, the Daleks-on-Doctor-Who effect), **tape delay** with feedback, and a **four-stage allpass phaser**. Each FX is written twice — once here in `slurmcore` for the eventual export, and once in JavaScript using the **Web Audio API** for the live preview the user hears while moving the sliders. The two implementations must sound identical, and an architecture decision record (one of twenty-three in the project) makes that requirement load-bearing: if you change one, you change both, in the same commit.

> ### **For the engineering reader**
>
> The strict separation between `slurmcore` (pure DSP), `slurmio` (filesystem), and the UI layer is enforced by review, not by the language. Any import of `os`, `sys`, `soundfile`, `gradio`, `shutil`, or `subprocess` inside `slurmcore.py` will get caught. The `apply_fx()` function takes `(y, sr, ...parameters)` and returns `(y, sr)`. The wrapper in the API layer (`burn_fx`) is the only place that loads, writes, or talks to the user.
>
> Channel layout convention is `(n_channels, n_samples)` — channels first — matching librosa. The two libraries that disagree (soundfile, pyrubberband) get transposes at the boundary. There is a one-line helper called `_stereo_pyrb` that wraps every Rubber Band call and is the *only* place the transpose happens. There is another, `_to_mono`, used before any call to `librosa.beat.beat_track` because librosa's beat tracker interprets a 2-D array as a multichannel onset envelope rather than as stereo audio. These are the kinds of decisions that don't break when you write them; they break, six months later, when a new feature touches them from a slightly different angle. Both have an ADR.

---

## IV. The trimodal distribution: a sidebar in three buckets

The most opinionated piece of code in `slurmcore` is also the simplest, and it is what gives `MAX RANDOM` mode its character.

Most software that randomizes durations does it in one of two boring ways. The first is **uniform**: pick a number between, say, 50 and 2000 milliseconds, all numbers equally likely. The second is **log-uniform**: pick a number such that each *order of magnitude* is equally likely (50–500 ms is as probable as 500–5000 ms). Either way, you produce a smooth, continuous distribution of durations.

The problem with this — and the engineers building Slurmify discovered it the way you discover most user-experience problems, which is by being told — is that smooth distributions don't sound random. They sound like a steady tempo with jitter. The ear, it turns out, is a categorical instrument. It hears bins, not gradients. A continuous distribution of slice durations produces an even gloss of blur; what you want, if you want surprise, is *categorically different* durations playing back-to-back.

Slurmify's `MAX RANDOM` resolves this by replacing the smooth distribution with a **trimodal** one. Three buckets:

| Bucket    | Range          | What it sounds like                                  |
|-----------|----------------|------------------------------------------------------|
| `stutter` | 5–30 ms        | An audio-rate blip; buzzy glitch texture             |
| `chop`    | 100–500 ms     | A recognisable rhythmic chunk; one syllable          |
| `held`    | 1000–4000 ms   | A long passage; the audio almost plays through       |

Each bucket has equal probability — each slice has a one-third chance of landing in each. Within a bucket the duration is log-uniform. The boundaries are hand-tuned, and the gaps between them — 30 to 100 ms, 500 to 1000 ms — are *not* filled in. The forbidden zones are the design.

What this means in practice is that consecutive slices are almost certainly drawn from different buckets, and the result sounds like genuine surprise. A 6 ms blip lands next to a 3-second held passage lands next to a 300 ms chop. The mind, deprived of intermediate sizes, reads the sequence as random.

The architecture decision record that documents this — ADR-0012, in the `docs/adr/` folder, alongside twenty-two siblings — opens with the user feedback that drove the change. *"max random still does not sound random,"* the user wrote. *"Are we truly respecting the slice parameter?"* The team's answer, in code, is the trimodal. The comment in `detect_slice_points` is sweet: *"Named after Max the tester (and 'maximum entropy')."*

---

## V. The rewrite

Slurmify version 0.2.0 — the current release as of May 2026 — is, on the inside, a different application than version 0.1.6. The change happened over the autumn and winter of 2025-2026.

The previous architecture used **Gradio**, a Python web framework that lets researchers ship machine-learning UIs in about thirty minutes. Gradio is a marvel for prototypes. It is *also*, the team learned, an opinionated and constantly-evolving framework whose conventions silently break custom JavaScript every few major versions. Slurmify's FX chain depends on the Web Audio API's `createMediaElementSource`, which has a quirk: it can be called exactly *once* per HTML audio element, for the lifetime of that element. Gradio's component lifecycle, which sometimes destroys and rebuilds the audio element on the fly, violated this rule constantly. The team kept a running document called `docs/adr/0014-gradio-quirks-collected.md`. By the time of the rewrite it had fourteen entries.

The new architecture is three pieces:

1. A **Tauri 2** Rust shell — a 5-megabyte native macOS application wrapper. (Electron, the better-known alternative, is closer to 150 megabytes for the same job.) The shell is responsible for opening the window, hosting a WebView, and spawning the backend.
2. A **React 19** + **Vite** + **TypeScript** frontend, running inside the WebView the Tauri shell hosts. State is managed by **Zustand** for cross-component data and React's built-in hooks for local state. Styling is **Tailwind**, theming via a single `data-skin` attribute on the body element.
3. A **FastAPI** sidecar process — the entire `slurmcore` Python codebase, packaged via **PyInstaller** into a single 100-megabyte binary that gets spawned as a subprocess at app launch.

The interaction protocol between the three pieces is small and clever. The sidecar picks an unused TCP port at startup (binding to port 0 and asking the OS to pick), prints a JSON ready-line to stdout — `{"slurmify_ready": true, "port": 56732}` — and then runs uvicorn. The Tauri Rust shell parses that line, stores the port in a discovery file in the system temp directory, and exposes it to the JavaScript side via a Tauri command. The React frontend reads the port on first mount and talks to the sidecar over plain HTTP and Server-Sent Events.

Long-running DSP jobs — a slurmify pass, a video render, an FX burn — use a **job pattern**. The frontend POSTs to `/slurmify`, gets a job ID back immediately, opens an SSE stream on `/jobs/{id}/progress`, and consumes a stream of `{progress, desc}` updates while the work happens in a background thread. This is the modern shape; it was substantially harder in Gradio.

The cost of the rewrite is one acknowledged piece of inelegance: PyInstaller's "onefile" mode, mandated by Tauri's sidecar contract (which only knows how to spawn a single executable, not a folder of them), self-extracts the bundle to a temp directory on every cold start. This adds three to five seconds to first-launch. The team has documented the tradeoff and accepted it for the tester DMG; production polish, if and when it lands, can revisit.

---

## VI. The four FX, and a video pipeline

After the slurmify pass, the user can optionally turn on the **FX accordion** — a four-section panel of sliders for **distortion**, **ring modulation**, **delay**, and **phaser**. As the user moves the sliders, the audio plays back through the Web Audio version of the chain in real time. When they hit "burn FX," the same chain runs in NumPy on the file, producing a new, processed audio file.

There is a **video export** button. It takes the final slurmified audio, mixes it under a 1.5-second pre-rendered MP4 of a 720p H.264 video loop, and produces a YouTube-ready MP4. The video track is *stream-copied* — not re-encoded — because re-encoding a 720p stream takes 30 seconds and stream-copying takes 0.4. The slurmify parameters used to produce the audio are encoded as JSON in the MP4's `description` metadata atom, which means a future version of the app could, in principle, open one of its own exports and reload the patch. ADR-0008 covers this.

---

## VII. The tester named Max, and the rest of the easter eggs

The codebase has a recurring proper noun: **Max**. Max is a specific person — the lone external tester who receives every DMG before public release. The `docs/TESTER_README.md` is addressed to him by name. The `MAX RANDOM` mode is named after him (and, as the comment notes, after maximum entropy). When you hover your mouse over the `MAX RANDOM` radio button, an animated GIF of Max's face slides out to the right. When you hover over the **dice button** (which randomizes every slider in one click), a different GIF — called Hoberman-Max, an animated spherical model of Max's face — pops up from the bottom. When you hover over the **reveal-temp-files button** (which opens the working folder in Finder), a third GIF, named **Bob**, springs up from below.

None of this is in the README. None of it is mentioned in the marketing copy, because there is no marketing copy. The first time you discover Max, or Hoberman-Max, or Bob, is by accident — by hovering over a button you didn't know would do anything. This is a deliberate choice, and an old one in software design. Microsoft Word once shipped a flight simulator hidden inside a spreadsheet. Slurmify ships three GIFs of a man's face. The point is the same: software gets used by humans, and humans like to discover things.

---

## VIII. The comments, which are the document

If you read the slurmify codebase, the thing that strikes you first is not the audio engineering. It is the *comments*.

Functions get section headers in box-drawing characters. The opening of `slurmcore.py` is a 100-line preamble explaining why the file exists, what it imports, what it doesn't, and what conventions it expects. Inside `detect_slice_points`, a constant called `DEFAULT_BPM = 120.0` carries a comment explaining that 120 was chosen because most contemporary music sits in the 100–140 BPM range and 120 is the value DAWs use as a starting tempo. Inside the trimodal sampler, a comment notes that the floor of 220 samples (≈ 5 ms at 44.1 kHz) was chosen because the envelope crossfade has no room to operate cleanly below that.

The `docs/adr/` folder, where the architecture decision records live, is an adjacent monument. There are twenty-three ADRs. Each is a short Markdown file explaining a single non-obvious decision — why MAX RANDOM uses three buckets instead of a smooth distribution, why all temporary files go through a single helper function, why the FX preview chain binds to a dedicated `<audio>` element exactly once. Each one is addressed to a future engineer, who might be the same engineer six months later and might be a stranger.

There is a project rule that a CLAUDE.md file at the repo root exists for collaboration with AI coding assistants. There is a project rule that AI assistants must read a precomputed code map called `AGENT_DIGEST.md` before doing anything else. There is a project rule that "the digest going stale is itself a signal worth noticing — it means the codebase has drifted from a state that was previously well-mapped."

This is not how most software gets written. It is how some software gets written. It tends to be the kind that lasts.

---

## IX. What it means

Tools shape what gets made. The slurmify trimodal distribution is an aesthetic argument disguised as a function: *here is the way we think audio should be randomized, and here is the way we think it should not.* The decision to put the four FX in the order distortion-ring-delay-phaser, rather than any of the twenty-three other possible orderings, is an aesthetic argument. So is the decision to make Rubber Band the time-stretcher rather than its open-source alternative SoX, or rather than the pitch-shifter built into librosa. Each of these is a hand on the steering wheel.

When you use a tool, you absorb its arguments. Use Slurmify a few hundred times and your output starts to *sound like Slurmify* — buzzy in the 5-30 ms range, blocky in the 100-500 ms range, occasionally quiet for two seconds at a stretch. A different tool, with different defaults, would produce something else. Granular synthesis as a *technique* is sixty-eight years old; the catalogue of tools whose particular knobs and ranges define the music made with them is longer than that.

The line goes, roughly, through Xenakis splicing tape on the floor of his Paris studio in 1958, through Curtis Roads writing FORTRAN at UC San Diego in 1974, through Markus Popp marking up CDs with X-Acto knives in 1991, through Native Instruments releasing the **Reaktor** modular environment in 1996, through countless plugins from Output and Arturia and iZotope through the 2000s and 2010s. It lands, today, on a MacBook running an unsigned 110-megabyte DMG, with a dancing cat GIF, in a folder called slurmify.

The cat does not need to be there. Neither do Max, Bob, or Hoberman-Max. The four-skin theming system, the ms ⇄ ♪ toggle, the embedded JSON metadata in the MP4 export — none of this is *necessary* in the sense that the program would fail to function without it. It is all decorative. It is all argument.

This is what good software looks like when nobody is making the people who write it cut anything.

---

## Glossary

- **Granular synthesis** — A technique for making sound by chopping audio into very small pieces (called *grains*) and rearranging them. Originated by Iannis Xenakis in 1958, computerized by Curtis Roads in 1974.
- **Time-stretching** — Changing how long an audio clip lasts without changing its pitch. The Rubber Band Library is one of the canonical implementations.
- **Transient** — A brief, sharp event in audio, like the attack of a drum hit or the consonant at the start of a syllable. Detecting transients is one of the hard problems in music information retrieval.
- **Bar mask** — A binary pattern (e.g., `[on, off, on, off]`) that mutes specific beat positions inside each bar. Slurmify exposes this as a row of clickable chips.
- **ADR** — Architecture Decision Record. A short Markdown document recording a single non-obvious engineering decision, with context and consequences. Slurmify has twenty-three of them.

---

## By the numbers

- **44,100 Hz** — internal sample rate (CD quality)
- **~2,000 lines** — slurmcore.py
- **23** — architecture decision records
- **3** — buckets in the MAX RANDOM trimodal distribution
- **4** — FX in the chain (distortion, ring, delay, phaser)
- **4** — visual skins (default, acid cathedral, hardware rack, +1)
- **3** — easter-egg hover GIFs (Max, Hoberman-Max, Bob)
- **1** — dancing cat (Siena, no relation)
- **1** — tester named Max

---

*Subvoyant SIENA Slurmer is open-source software, released under the GNU General Public License v3.0. The project lives at the studio's repository and ships as an unsigned macOS DMG. Version 0.2.0 is the current release. A signing-and-notarization workstream is reportedly underway.*

## Sources

- [Rubber Band Library — Breakfast Quay](https://breakfastquay.com/rubberband/)
- [Granular Synthesis — Iannis Xenakis Foundation](https://www.iannis-xenakis.org/en/granular-synthesis/)
- [Granular synthesis — Wikipedia](https://en.wikipedia.org/wiki/Granular_synthesis)
- [Synthesis Methods Explained: What is Granular Synthesis? — Perfect Circuit](https://www.perfectcircuit.com/signal/what-is-granular-synthesis)
- [A Guide to Oval's Digital Evolution — Bandcamp Daily](https://daily.bandcamp.com/lists/oval-album-guide)
- [Oval (musical project) — Wikipedia](https://en.wikipedia.org/wiki/Oval_(musical_project))
- [Glitch (music) — Wikipedia](https://en.wikipedia.org/wiki/Glitch_(music))
