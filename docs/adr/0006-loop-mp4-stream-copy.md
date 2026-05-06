# ADR-0006: Pre-encoded loop MP4 + stream-copy for video export

- **Status:** Accepted
- **Date:** 2026-05-04

## Context

The YouTube MP4 export needs to play a short looping animation
(36 frames, ~1.5 s) over the slurm output's audio for the duration of
the song. The animation source is a frame sequence rendered out of
After Effects.

**First implementation** read the PNG sequence directly with ffmpeg's
`image2` demuxer and `-stream_loop -1`, scaled to 1920×1080 with
Lanczos, then re-encoded the result as H.264 with `-preset medium`
`-crf 22`.

This worked but was painfully slow. Reasons in order of cost:

1. **PNG decode is ~10–50× slower than H.264 decode.** PNG is general-
   purpose lossless DEFLATE compression with per-frame stand-alone
   decoding; H.264 has inter-frame prediction so most frames are
   nearly free to decode.
2. **`-stream_loop -1` on a PNG sequence re-decodes from disk on
   every loop pass.** For a 3-minute song at 24 fps that's
   ~120 passes × 36 PNGs = ~4,300 PNG decodes. Each PNG was 1.6 MB
   on disk and ~3.5 MB of RGBA in memory.
3. **Lanczos upscale from 1280×720 to 1920×1080** had to run for
   every single output frame.
4. **`-preset medium` H.264 encode** is unhurried by design.

Total: a 3-minute render took >100 s on a modern Mac and timed out at
45 s on the sandbox CPU even for 30 s of audio. The user noticed.

## Decision

1. **Pre-encode the loop animation as a 1920-source-1280×720 H.264
   MP4 once,** kept in `assets/siebaSlurm_A003.mp4`. CRF 30 because
   the VHS-aesthetic chromatic aberration is already noisy by
   design — compression artifacts read as "more tape grain."
   Resulting file: ~330 KB.
2. **Stream-copy the video at render time.** `-c:v copy`. ffmpeg
   demuxes the H.264 packets out of the loop file, multiplies the
   loop via `-stream_loop -1`, and remuxes them into the output
   container. **No video re-encoding.**
3. **Audio is encoded to AAC as before** (192 kbps / 48 kHz).

The PNG sequence stays in `graphic/siebaSlurm_A003/` as the
"source of truth"; only the MP4 ships in the bundle.

## Consequences

**Wins**

- Render time drops from ~100 s to ~0.1 s for a 30-second clip.
  Stream-copy is essentially free; the AAC audio encode is the
  bottleneck.
- Bundle is ~58 MB smaller (PNGs gone).
- Output file size at the new defaults is ~40 MB for a 3-minute song
  (was 250+ MB with the old re-encode pipeline at preset medium / CRF
  22).

**Costs**

- Loop quality is fixed at MP4-encode time. To change quality (or
  resolution), regenerate the MP4. The exact ffmpeg one-liner lives
  in a comment block at the top of `render_video()`.
- Output bitrate is whatever the loop file's bitrate is. Can't be
  dialed at export time without re-encoding (which would defeat the
  speedup).

## Trade-off table

Captured during selection (all CRF 30, 1280×720, slow preset):

| Source fps | Output fps | Loop size | 3-min output | Notes |
|---|---|---|---|---|
| 24 | 24 | 0.3 MB | ~ 40 MB | Original speed ("dancer too jumpy") |
| 8  | 12 | 0.7 MB | ~ 28 MB | Dancer 1/3 speed via 1.5× B-frame duplicates |
| 8  | 8  | 0.8 MB | ~ 31 MB | Dancer + container both at 8 fps (chosen briefly) |
| **12** | **12** | **0.6 MB** | **~ 35 MB** | ← **current**: classic cell-animation rate |

The current choice plays the source PNGs at 12 fps — the traditional
"animation on twos" rate used by Disney, Warner Bros, and most
hand-drawn animation studios. 36 frames at 12 fps = 3.0 s loop, half
the speed of the 24 fps source. The output container also runs at
12 fps, so there's no rate conversion or duplicate frames. Slightly
larger 3-min output than 8 fps (50 % more frames per second of audio),
but the motion reads as deliberately animated rather than glitchy.

Source PNGs are 1280×720 — upscaling to 1080p adds zero information
and YouTube re-encodes everything anyway, so the bytes spent on 1080p
are wasted.

## When to revisit

- New animation source at a different framerate or resolution → just
  re-run the regeneration ffmpeg from the comment with the right
  scale/framerate.
- Quality complaints from users → bump to CRF 26 or 24 (factor-of-2
  size hit). Frames I extracted at CRF 30 were visually
  indistinguishable from source for this content; YMMV for less noisy
  animation.
- Need different output bitrates per render call → would have to
  switch back to re-encode. The right place would be a `quality=` arg
  on `render_video()`; default to stream-copy, opt-in to re-encode.

## See also

- `app.py` `render_video()` — the regeneration ffmpeg in the header
  comment, the stream-copy command at the bottom
- `assets/siebaSlurm_A003.mp4` — current loop file
- `graphic/siebaSlurm_A003/` — source PNG frames (not bundled)
