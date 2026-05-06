# ADR-0012: MAX RANDOM uses a trimodal distribution, not log-uniform

- **Status:** Accepted
- **Date:** 2026-05 (v0.1.0)

## Context

`MAX RANDOM` is a slice-resolution mode that bypasses the BPM grid
entirely and emits random slice durations. The goal is for the result
to actually *sound* random and chaotic — categorically different from
the regular grid resolutions.

We tried, in order:

1. **Single-rate position sampling.** Pick one rate (4-40 slices/sec),
   then place that many random sample positions across the audio.
   Resulting gaps follow an exponential distribution around `1/rate`
   ms. Audibly: sounds like a constant chop tempo with statistical
   jitter — *not* what users perceive as "random."

2. **Continuous log-uniform between 5 ms and 5000 ms.** Each slice's
   duration is independently `10**uniform(log10(5), log10(5000))` ms.
   Mathematically wide-range (1000× span) and looks great in a
   distribution plot. But audibly the result still sounds like a
   constant chop tempo, because:
   - ~40% of slices land in 50–500 ms (chop-tempo range)
   - The ear blends those 40% into a steady percussive feel
   - The 5–20 ms outliers are all just "click" textures — the listener
     can't tell a 5 ms slice from a 15 ms slice
   - The 1000+ ms outliers are too rare (~10%) to feel intentional
   - Net perception: medium chops with occasional weirdness

The user's specific feedback after testing the log-uniform version:
*"max random still does not sound random. Are we truly respecting the
slice parameter?"* — confirming that log-uniform's middle-ground
saturation overwhelms the audible variation.

## Decision

**Trimodal distribution: three categorical buckets, equal probability,
each log-uniform within. Skip the in-between values entirely.**

```python
BUCKETS = [
    ("stutter", 5.0,    30.0),    # audio-rate buzz, glitch bursts
    ("chop",    100.0,  500.0),   # recognizable rhythmic chunks
    ("held",    1000.0, 4000.0),  # long passages, almost plays through
]
positions = [0]
pos = 0
while pos < len(y):
    name, lo_ms, hi_ms = random.choice(BUCKETS)
    dur_ms = 10.0 ** random.uniform(np.log10(lo_ms), np.log10(hi_ms))
    dur_samples = max(220, int(sr * dur_ms / 1000.0))
    pos += dur_samples
    if pos < len(y):
        positions.append(pos)
```

Three deliberate omissions:

- **No 30–100 ms range.** That's the "fast chop" zone — would dominate
  the perception and undo the categorical contrast.
- **No 500–1000 ms range.** That's the "mid phrase" zone — would
  blend chop and held categories together.
- **No values above 4000 ms.** Keeps the longest slices recognizable
  as held passages without becoming "the audio just plays through."

## Consequences

**Wins**

- **Audibly random.** Consecutive slices are categorically different
  durations: a 5 ms stutter next to a 2.4-second held vowel next to
  a 200 ms chop. No tempo emerges; the ear gives up trying to
  predict.
- **Each category does its own thing musically:**
  - Stutters cluster naturally into glitch bursts (bucket-rolling
    independence means runs of 2-3 stutters are common)
  - Chops feel like recognizable beats
  - Held passages give the ear a breather, then the next stutter
    burst hits hard by contrast
- **Reproducible.** All sampling goes through Python's `random`
  module which is seeded by the slurmify entrypoint. Same seed +
  same input = bit-identical chaos sequence.
- **Debuggable.** A startup print reports per-bucket counts — verifies
  the distribution is balanced (`stutter=N chop=N held=N` should be
  roughly equal).

**Costs**

- **Median slice drops to ~92 ms** (vs ~159 ms for log-uniform). Fewer
  total slices per source because the bucket math averages out to
  longer mean duration.
- **Hand-tuned bucket boundaries.** Not derived from theory — picked
  empirically because they sound good. If a future user has a use
  case that wants medium chops or super-long passes, they can't get
  it from MAX RANDOM (they should use 1/8 or 1/2 instead).
- **No way to control the bucket weights** from the UI — fixed at
  33/33/33. Adding sliders for per-bucket weight is possible but
  starts to defeat the "MAX RANDOM = no decisions" UX promise.

## Risks

- **The bucket boundaries are fragile.** If someone "improves" them
  to e.g. 10–60 / 60–400 / 400–3000, they fill the middle and the
  audible randomness dies. The current values are chosen because
  the *gaps between buckets* are the load-bearing design element,
  not the values within each bucket.
- **220-sample floor (~5 ms at 44.1 kHz)** is a hard limit imposed
  by the slice envelope crossfade — sub-220-sample slices are
  mostly fade with no audible content. If the floor is raised, the
  stutter bucket loses its character.

## See also

- `app.py` `detect_slice_points` — the trimodal branch under
  `if resolution == "MAX RANDOM"`
- ADR-0013 (auto-shuffle on MAX RANDOM) — partner decision; without
  shuffle, the trimodal categories play in source order and the
  contrast is much less audible
- `SLURMCORE_COMPARISON.md` §3.4 — user-facing explanation of the
  trimodal approach
