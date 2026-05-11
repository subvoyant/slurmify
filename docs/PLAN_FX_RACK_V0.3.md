# FX Rack v2 — v0.3 Release Plan

> **Status:** drafting · **Target:** v0.3.0 · **Last updated:** 2026-05-11

The v0.3 release closes the long-standing frontend↔backend FX-parity
gap and adds one new effect (pitch shifter). All three user-facing
changes — pitch shifter in the rack, beat-mode toggle on the panner
sweep rate, and "what you hear in live preview is what you get when
you burn" — are tightly coupled architecturally, so they ship as one
release rather than three small ones. Reasoning is below.

---

## 1. Background — the FE/BE parity gap

Today the React live-preview FX chain (`src/hooks/useFxChain.ts`) is
richer than the Python burn-fx chain (`slurmcore.py::apply_fx`):

| Effect                        | Live preview (Web Audio) | Burned output (slurmcore) |
| ----------------------------- | ------------------------ | ------------------------- |
| Distortion (gain/drive/tone)  | ✓                        | ✓                         |
| Ring mod (with sweep)         | ✓                        | ✓                         |
| **Tremolo**                   | **✓**                    | **✗**                     |
| **Auto-panner (with sweep)**  | **✓**                    | **✗**                     |
| Delay (with feedback)         | ✓                        | ✓                         |
| Phaser (4-stage allpass)      | ✓                        | ✓                         |
| **Reverb**                    | **✓**                    | **✗**                     |
| **Pitch shifter** (NEW)       | **— add —**              | **— add —**               |

When a user dials in tremolo or panner in live preview, then clicks
**burn FX** or **render YouTube MP4**, those three effects silently
vanish from the output. The bake is essentially "burn the four
effects we happen to have ported to Python." That's the disease.

v0.3 cures it AND adds pitch shifter, which is the simplest place to
also exercise the new effect-addition surface so we don't have to
repeat the boilerplate three times.

---

## 2. Scope summary

| # | Change                                                                    | Owner    |
| - | ------------------------------------------------------------------------- | -------- |
| 1 | Port tremolo to Python `apply_fx` (so it bakes into burn-fx output)       | backend  |
| 2 | Port auto-panner to Python `apply_fx`                                     | backend  |
| 3 | Port reverb to Python `apply_fx`                                          | backend  |
| 4 | Add pitch-shifter as a new FX-rack effect (UI + Web Audio + Python)       | both     |
| 5 | Add beat ↔ ms toggle to every rate/time FX param that lacks one          | both     |
| 6 | Refactor the FX-effect-addition surface so future effects need 1 file ea. | both     |

Out of scope for v0.3: beat-mode on ring sweep rate (user was explicit
— only panner sweep speed gets the toggle), beat-mode on phaser rate
(no user request), spectrograms, XY pads, import-patch-from-MP4.

---

## 3. Detailed designs

### 3.1 Pitch shifter as an FX-rack effect

**Position in the user's mental model.** The user described this as
"after the fact — added with other effects onto slurm playback." That
means it lives in the FX rack alongside distortion/delay/etc., applied
during burn-fx (and during live preview), NOT in the pre-slurmify
pipeline. There IS already a `pitch_shift_semitones` parameter on the
slurmify endpoint (slurmcore.py:711, applied pre-slice at line 952);
that's a different feature ("tune the source key before slurmifying")
and stays as-is. The new FX-rack pitch shifter is independent.

**Position in the signal chain.** Decided (2026-05-11): pitch shifter
sits **immediately before reverb**, so the order is:

  distortion → ring → tremolo → delay → phaser → **pitch shifter** → reverb

Reason: the reverb tail blooms from the *pitched* signal, which gives
the chain the "smear a pitched cloud into space" character that's
most musically interesting. Putting pitch BEFORE the reverb (rather
than after, my original proposal) keeps the reverb as the final
"acoustic space" stage, which is conventional and intuitive.
Performance is identical — pyrubberband still runs once per burn-fx
call regardless of position.

**Web Audio implementation.** Web Audio has no built-in pitch-shift
node. Three options:

| Option                                | Latency | Quality | Cost     |
| ------------------------------------- | ------- | ------- | -------- |
| `playbackRate` on the audio element   | 0       | Bad — changes speed AND pitch | Free |
| AudioWorklet phase-vocoder            | ~20 ms  | Good    | ~200 LoC |
| `soundtouchjs` library                | ~30 ms  | Good    | +160 kB to bundle |

**Recommended:** AudioWorklet phase-vocoder. Adds zero dependencies,
matches the spirit of "no external deps in the React app where we can
avoid them" (current FX chain is pure Web Audio). ~200 lines of code
lives in `src/audio-worklets/pitch-shifter.ts`.

**Python implementation.** `pyrubberband.pitch_shift(y, sr, n_steps)`.
Already a backend dependency (used by slurmify). Same `_stereo_pyrb`
shape-juggling wrapper that the existing pre-slurm pitch shift uses
(see slurmcore.py:256-275, ADR-0021).

**UI controls (rack subcomponent):**
- **enabled** — bypass toggle.
- **semitones** — knob, range **−24 to +24**, default 0, step 1.
  Coarse pitch. (Standard musical octave-bidirectional range.)
- **fine** — knob, range **−100 to +100** cents, default 0, step 1.
  Optional second knob; if it adds UI clutter we can defer to v0.3.1.
  Decision: include it. Cents shift musicians-who-care will use.
- **mix** — knob, 0–100 %, default 100 %. Wet-only by default makes
  sense (you want to hear the pitch-shifted version) but a wet/dry
  blend opens up doubler effects, so we expose the knob.

**FX request schema additions** (`src-python/api/fx.py`):
```python
pitch_enabled:   bool = False
pitch_semitones: float = 0.0     # -24 to +24
pitch_fine:      float = 0.0     # -100 to +100 cents
pitch_mix:       float = 1.0     # 0.0 dry to 1.0 wet
```

**fxStore additions** (`src/stores/fxStore.ts`):
```ts
pitchEnabled:    boolean   // default false
pitchSemitones:  number    // default 0,  range [-24, +24]
pitchFine:       number    // default 0,  range [-100, +100]
pitchMix:        number    // default 1.0
```

---

### 3.2 Beat ↔ ms toggle on every rate/time FX param

**User intent (2026-05-11).** Beat-mode is the standard pattern for
any rate-like or time-like FX param across the rack. Today only
tremolo rate and delay time have it; v0.3 brings ring sweep rate,
panner sweep rate, and phaser LFO rate up to parity. (User confirmed
"keep on all others" after I misread an earlier scoping question.)

**Within the panner subrack specifically:** the sweep RATE gets the
toggle. The OTHER panner controls — spread L, spread R, mix, sweep
waveform — do not (they're not rate/time parameters). This subtlety
was the source of the original miscommunication.

**Pattern reference.** Already implemented for `tremoloRate`
(`fxStore.ts:122`) and `delayTime` (`fxStore.ts:171`). Mimic the
pattern verbatim. For each new param `<x>Rate`, add:

```ts
<x>RateMode: "Hz" | "♪"     // default "Hz" (or "ms" for time params)
<x>RateNote: string          // default "1/4"
```

**Params getting the toggle in v0.3:**

| fxStore field          | Current type | Adds mode field?            | Notes |
| ---------------------- | ------------ | --------------------------- | ----- |
| `tremoloRate`          | Hz           | already has `tremoloRateMode` | no change |
| `delayTime`            | ms           | already has `delayTimeMode`   | no change |
| `ringSweepRate`        | Hz           | **NEW** `ringSweepRateMode` | follow tremolo pattern |
| `pannerSweepRate`      | Hz           | **NEW** `pannerSweepRateMode` | follow tremolo pattern |
| `phaserRate`           | Hz           | **NEW** `phaserRateMode`    | confirm field name in code; follow tremolo pattern |

**Reverb decay** stays a free-running seconds value with no beat-mode
toggle. Decision confirmed 2026-05-11 — decay is a duration not a
rate, and beat-locked decay isn't a musically intuitive parameter.

**Note grammar** is the one defined in `slurmcore._note_to_ms`
(slurmcore.py:153). Python is source of truth per ADR-0020. JS side
mirrors it for the live "≈ N Hz @ BPM" hint. Changing the grammar in
one place means changing it in the other in the same commit — same
discipline ADR-0020 already enforces.

**Conversion.** `note → seconds = beats × (60 / BPM)`, then
`Hz = 1 / seconds` for rate params, or `ms = seconds × 1000` for time
params. Example at 120 BPM: "1/4" note → 0.5 s → 2 Hz / 500 ms.

**BPM source.** The slurmify-detected BPM (returned alongside slice
positions per ADR-0020). If no slurmify has been run yet — the user
is twisting FX in standalone live preview — we default to 120 BPM
and surface that in the hint text.

**UI:** swap each ring/panner/phaser rate knob for a `KnobNoteToggle`
composite component — same one tremolo and delay already use.

---

### 3.3 Tremolo backend port

**Existing Web Audio impl** (`src/hooks/useFxChain.ts:617+`):
- Sinusoidal LFO multiplies amplitude.
- `tremoloRate` (Hz or note), `tremoloDepth` (0–1), `tremoloPhase`
  (L vs R phase offset for stereo widening).
- A small "wandering" noise source can be mixed in via
  `tremoloNoiseAmt` for "sample-and-hold-ish" character.

**Python port** (new function `_tremolo` in slurmcore.py):
```python
def _tremolo(y, sr, *, rate_hz, depth, phase_offset, noise_amt):
    """LFO amplitude modulation.  Stereo-aware: y can be (n,) or (2, n)."""
    n = _n_samples(y)
    t = np.arange(n, dtype=np.float64) / sr
    # Sinusoidal LFO, depth-scaled amplitude modulator.  At depth=0 we
    # output passthrough (mod=1.0 everywhere); at depth=1 we modulate
    # between 0 and full signal.  At intermediate depths the LFO is
    # offset so the carrier never inverts — equivalent to a "DC + AC"
    # envelope rather than ring-mod-style bipolar modulation.
    lfo_left  = (1.0 - depth) + depth * 0.5 * (1.0 + np.sin(2 * np.pi * rate_hz * t))
    if y.ndim == 2:
        # Stereo: apply a phase offset to the right channel for width.
        lfo_right = (1.0 - depth) + depth * 0.5 * (1.0 + np.sin(2 * np.pi * rate_hz * t + phase_offset))
        out = np.stack([y[0] * lfo_left, y[1] * lfo_right])
    else:
        out = y * lfo_left
    return out.astype(np.float32)
```

Cost: ~30 lines. Pure NumPy, no SciPy required (matches the slurmcore
"keep apply_fx hot path light" posture from ADR-0016).

---

### 3.4 Auto-panner backend port

**Existing Web Audio impl** uses `createStereoPanner` with an LFO
modulating the pan position. fxStore params:
- `pannerEnabled`, `pannerMix`
- `pannerSweepRate` (Hz; v0.3 gets beat-mode per §3.2)
- `pannerSpreadL` and `pannerSpreadR` — these are the *maximum* pan
  excursions to L and R (allows asymmetric ping-pong)
- `pannerSweepWave` ("sine", "triangle", "square", "noise")

**Python port** (new `_panner` in slurmcore.py): same LFO machinery
as tremolo, but the LFO drives a pan position p ∈ [−1, +1] which
scales L/R gains. Stereo input only — for mono we duplicate to L/R
first (matches the live preview's behaviour).

```python
def _panner(y, sr, *, rate_hz, spread_l, spread_r, wave, mix):
    """Auto-panner with asymmetric L/R spread and waveform-shaped LFO."""
    # spread_l/spread_r are 0..1 maxima; the LFO sweeps in [-spread_l, +spread_r]
    # ...sin/triangle/square/noise dispatch...
    # ...constant-power pan law: gain_l = cos((p+1) * π/4); gain_r = sin((p+1) * π/4)...
```

Cost: ~60 lines. Adds `noise` LFO option (numpy.random.default_rng
with a seeded RNG so it's reproducible per-job).

---

### 3.5 Reverb backend port

**This is the hardest port** because reverb has the most algorithmic
variation. The Web Audio impl uses a `ConvolutionNode` with a small
generated IR. Three Python options:

| Algorithm           | Pros                         | Cons                         |
| ------------------- | ---------------------------- | ---------------------------- |
| Freeverb (Schroeder + Moorer parallel-comb + serial-allpass) | Procedural, no IR file needed, well-known sound, lightweight | ~120 LoC; tuning artisanal |
| `scipy.signal.fftconvolve` with bundled IR WAV | Sounds great, easy code | Adds an IR file to bundle; one IR only unless we ship many |
| Schroeder (4 comb + 2 allpass) | Classic, very lightweight, ~50 LoC | Sound is "boxy" — fine for a tester but not flagship |

**Recommended:** **Freeverb**. Industry standard for procedural
reverb in C/C++/Python plugins; sounds neutral; tunable via the
existing `reverbDecay` / `reverbMix` UI params; no extra bundle
weight; matches the spirit of "all FX live in slurmcore as pure
NumPy/SciPy code, no resource files."

Implementation reference (well-trodden ground; many public-domain
Python ports exist). Expected code size: 100-150 lines, including the
8 comb + 4 allpass tunings and stereo widening.

**fxStore alignment.** Existing fields are:
- `reverbEnabled`, `reverbMix`, `reverbDecay` (or `reverbRoomSize`),
  `reverbDamping`, `reverbWidth` — verify exact names against current
  store at implementation time.

---

### 3.6 The "add-an-FX-effect" refactor (§ Scope #6)

Today, adding one new FX-rack effect requires touching:

1. `src/stores/fxStore.ts` — new fields + defaults.
2. `src/components/<name>Rack.tsx` — new rack subcomponent.
3. `src/hooks/useFxChain.ts` — new Web Audio nodes + wiring.
4. `src-python/api/fx.py` — request schema fields + wire into call.
5. `slurmcore.py::apply_fx` + a new `_<name>()` DSP function.

Five files per effect. Adding three at once (pitch + bringing tremolo
and panner over) means 15 file-edits if done serially. Worth pulling
out:

- An `FxEffectDef` type that bundles defaults, request schema fragment,
  and rack-component metadata so adding effect #N+1 is closer to one
  module.
- Defer if it adds risk — the goal is shipping v0.3, not perfecting
  the abstraction. If the refactor is more than a day, skip it for
  v0.3 and revisit in v0.3.1.

---

## 4. Implementation phases

Suggested ordering, smallest-first so each phase produces a shippable
mini-release if we want to chunk it:

**Phase 1 — Beat-mode on panner (smallest, well-understood).**
Mirrors the existing tremolo/delay pattern exactly. ~half a day. No
algorithmic risk. Ship as v0.3-rc1 if we want a tester checkpoint
before the heavier ports.

**Phase 2 — Tremolo + panner Python ports.** Pure-NumPy DSP. ~1 day
including A/B parity test (live preview vs burned output for the
same params should be perceptually identical). Ship as v0.3-rc2.

**Phase 3 — Reverb Python port (Freeverb).** ~1.5 days. Highest
algorithmic risk; will need iterating until the burned reverb tail
matches the live preview's character. Ship as v0.3-rc3.

**Phase 4 — Pitch shifter end-to-end.** ~2 days (AudioWorklet on the
JS side is the largest chunk). Ship as v0.3.0 final.

Total: ~5 dev days plus testing rounds. Realistic ~1-2 weeks
elapsed once Bob and Max feedback comes in.

---

## 5. Test plan

For each phase:

1. **Live-preview unit test:** load a known reference clip (a short
   sustained piano note), enable only the new effect, ear-confirm the
   sound matches expectations.
2. **Burn-fx A/B parity:** for each ported effect, burn the same
   reference clip and compare to the live preview. Use the slurmify
   reveal-temp button to grab the burned WAV, diff its waveform
   against a screenshot of the live preview waveform at the same
   playhead. Goal: indistinguishable to ear.
3. **YouTube render carries through:** the v0.2.1 "FX-burned default
   for renders" should mean any new effect that bakes correctly into
   burn-fx will automatically appear in rendered MP4s. Verify
   anyway with a 30 s test render.
4. **Tester round:** Bob + Max get a "what's new" doc + the build, a
   weekend to play, structured feedback form. Same cadence as v0.2.1.

---

## 6. Risks & mitigations

- **AudioWorklet pitch shift is complex.** If implementation slips,
  ship Python-only pitch for v0.3 (burns work but live preview shows
  no pitch effect) and add AudioWorklet in v0.3.1. The user gets the
  burned output capability immediately.

- **Reverb tail divergence between WA and Python.** Convolution-based
  Web Audio vs Freeverb-based Python will not sound identical. Two
  fallbacks: (a) we accept it as "close enough" for a beta, (b) we
  port the Python side to also use convolution with a shared IR.
  Decide after first A/B.

- **Performance — pyrubberband subprocess per burn.** Pitch shift adds
  another rubberband call to every burn (existing slurmify already has
  one). For typical 3-minute audio that's ~2 seconds extra. Acceptable.

- **JSON SSE payloads carry strings with non-ASCII** (note glyph "♪").
  Already handled — `json.dumps` escapes by default. Reconfirmed
  during the v0.2.1-win-5 Windows-charmap investigation.

---

## 7. Open questions for the user

All five v0.3-defining decisions confirmed with the user 2026-05-11:

1. **Pitch shifter signal-chain position:** immediately BEFORE reverb
   (so reverb tail blooms from pitched signal). ✓
2. **Pitch shifter range:** −24 to +24 semitones PLUS −100 to +100
   cents (two knobs). ✓
3. **Reverb algorithm:** Freeverb. ✓
4. **"Mix" semantics on pitch:** dry/wet blend. ✓
5. **Beat-mode scope:** every rate/time FX param that lacks one
   (ring sweep rate, panner sweep rate, phaser LFO rate), in
   addition to the existing tremolo + delay. ✓

6. **Beat-mode on reverb decay:** SKIP. Decay stays a free-running
   seconds value. Confirmed 2026-05-11.

**All design decisions locked. Spec is ready to implement.**

---

## 8. Touched-files manifest

```
NEW
  src/audio-worklets/pitch-shifter.ts        — phase-vocoder worklet
  src/components/PitchShifterRack.tsx        — new rack subcomponent
  docs/PLAN_FX_RACK_V0.3.md                  — this file
  docs/adr/0026-fx-rack-v2.md                — architectural record

EDIT
  src/stores/fxStore.ts                      — new fields + defaults
  src/hooks/useFxChain.ts                    — wire pitch + ensure panner/
                                               tremolo/reverb call out the
                                               same params Python expects
  src/components/PannerRack.tsx              — beat-mode toggle
  src/components/FxRack.tsx                  — insert PitchShifterRack
  src-python/api/fx.py                       — request schema additions
  slurmcore.py                               — _tremolo, _panner,
                                               _reverb, _pitch funcs,
                                               wire into apply_fx
  src-tauri/tauri.conf.json                  — version bump 0.2.1→0.3.0
  package.json                               — version bump
  src-python/pyproject.toml                  — version bump
  docs/TESTER_README.md                      — "What's new in v0.3"
  docs/TESTER_README_WINDOWS.md              — same
  AGENT_DIGEST.md                            — update FX-chain map
```

---

*End of plan.*
