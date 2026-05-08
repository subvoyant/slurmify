# ADR-0021: Stereo end-to-end through the slurmify pipeline

- **Status:** Accepted
- **Date:** 2026-05
- **Version:** 0.1.6

## Context

Until v0.1.5, the slurmify pipeline forced every input to mono.
`load_audio` called `librosa.load(..., mono=True)` regardless of the
source, and `slurmify()` assumed 1-D arrays everywhere downstream.
A stereo source uploaded by the user produced a mono slurm output,
losing whatever stereo image the source had — pads, panning, doubled
guitars, drums with stereo overheads, etc.

The user asked for stereo end-to-end: stereo in → stereo out, with
the L/R relationship preserved through the slicer, time-stretcher,
pitch-shifter, FX chain, and final write.

## Decision

### Channel layout convention

Slurmcore stores audio as **(n_channels, n_samples)** for multichannel
("channels first") and **(n,)** for mono.  This matches:

- librosa's documented convention for multichannel arrays.
- The existing `_fx_*` helpers (`_fx_distortion`, `_fx_ring_mod`,
  `_fx_delay`, `_fx_phaser`) which already accepted both shapes.

Two libraries we touch use the OPPOSITE convention — channels-LAST,
shape **(n_samples, n_channels)**:

- **soundfile** (used inside `slurmio._write_audio`).
- **pyrubberband** (`pyrb.time_stretch` and `pyrb.pitch_shift`).

Transposes happen at the module boundaries:

| Boundary                            | Transpose? |
|-------------------------------------|-----------|
| `slurmify` → `process()`            | No (caller does it) |
| `process()` → `_write_audio`        | **Yes** — `y.T` for 2-D |
| `slurmify` ↔ `pyrubberband`         | **Yes** — `_stereo_pyrb` wraps it |
| `apply_fx` → `burn_fx` → `_write_audio` | **Yes** — `y.T` for 2-D |

Mono (1-D) arrays pass through unchanged in either convention.

### Shape-agnostic primitives in slurmcore

Three new helpers near the top of `slurmcore.py` keep the pipeline
shape-agnostic without `if y.ndim == 1` branches everywhere:

- `_n_samples(y)` — returns `y.shape[-1]`.  Use this instead of `len(y)`,
  which would return the channel count for a 2-D array.
- `_to_mono(y)` — returns a 1-D mixdown (channel mean) for librosa's
  beat tracker and onset detector, both of which expect mono input.
- `_stereo_pyrb(fn, y, sr, *args)` — wraps a pyrubberband call with the
  correct transposes around the channels-LAST boundary.

The `slurmify()` body and `apply_envelope()` were rewritten to:

- Use `_n_samples` instead of `len`.
- Use ellipsis indexing (`y[..., a:b]`, `s[..., :n_fade]`,
  `s[..., ::-1]`) so time-axis operations apply correctly to both
  shapes.
- Use `np.tile(s, (1, n))` for stereo (vs `np.tile(s, n)` for mono) so
  only the time axis repeats.
- Use `np.concatenate(processed, axis=-1)` so the time axis joins
  while channels stay separate.
- Build the beat-gap silence block to match the slices' channel
  layout: `np.zeros((channels, gap_n))` for stereo,
  `np.zeros(gap_n)` for mono.

For the chipmunk-mode resample, `np.interp` only handles 1-D, so for
stereo we loop per channel and stack back into `(channels, n)`.

### Beat detection on the mono mixdown

`librosa.beat.beat_track` and `librosa.onset.onset_detect` interpret
2-D input as a multichannel onset envelope, which is not what we want
for tempo estimation.  `detect_slice_points` now mixes down to mono
via `_to_mono(y)` and passes that to both detection functions.  The
detected slice positions are sample indices along the (shared) time
axis, so they apply correctly to the original stereo `y`.

This is industry standard: every beat tracker we surveyed (madmom,
Essentia, Sonic Visualiser) operates on a mono mixdown internally.

### load_audio default

`slurmio.load_audio(path, *, mono=False)` — the default flipped from
`mono=True` to `mono=False` so the slurm pipeline preserves source
channels.  Callers can still pass `mono=True` to force a mono load.

A mono source returns shape `(n,)` (librosa's own behaviour); a stereo
source returns shape `(2, n)` — channels-first, matching slurmcore's
convention.  No transposes needed at this boundary.

## Latent bug fixed

`burn_fx` previously contained the comment "_write_audio handles it"
above an `else: export = y` branch that left stereo as `(channels, n)`
when passing to `_write_audio`.  Soundfile actually expects
`(n, channels)` for stereo, so any stereo input would have written a
file with the wrong shape (a 2-sample file with hundreds of thousands
of channels).  The bug never surfaced because the slurm pipeline
forced mono — `burn_fx` was only ever called on mono audio.

The v0.1.6 fix transposes at this boundary too: `export = y.T`.

## Consequences

**Pros**

- Mono source → mono slurm output (file size unchanged from v0.1.5).
- Stereo source → stereo slurm output (file size doubled, as expected).
- Stereo image — pads, panning, doubled tracks, ambient stereo
  reverb tails, drum overhead positioning — survives end-to-end.
- The `_fx_*` chain was already stereo-aware, so no FX changes were
  needed.  The stereo `(channels, n)` convention is now uniformly
  enforced across slurmcore.

**Cons / future work**

- Stereo doubles the memory footprint and processing time of every
  pipeline stage.  Long-form stereo files (>10 min at 44.1 kHz) will
  be noticeably slower than the mono path.  No mitigation in v0.1.6;
  if it becomes a problem, a "downmix to mono" UI toggle could be
  added (channel-aware code is already in place to support it).
- pyrubberband's stereo mode is "channel-coupled" by default, which
  is what users expect for music.  If a future release wants
  per-channel independent stretching (a creative effect), it would
  need the `--no-coupled` flag passed via `rbargs`.

## References

- [ADR-0008](0008-self-describing-mp4.md) — PATCH metadata; channel
  count is implicit in the embedded audio.
- [ADR-0016](0016-slurmcore-dsp-extraction.md) — established
  slurmcore's purity rule and the `_fx_*` shape contract that this
  ADR generalises to the rest of the module.
- [ADR-0017](0017-slurmio-filesystem-extraction.md) — `load_audio`
  lives in slurmio; the channel-preservation default change is in
  this module.
- [pyrubberband source](https://github.com/bmcfee/pyrubberband/blob/master/pyrubberband/pyrb.py)
  — confirms the `(n,)` or `(n, c)` channels-LAST shape contract.
