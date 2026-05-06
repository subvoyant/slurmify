# ADR-0009: Universal upload via `gr.File`, not `gr.Audio` for input

- **Status:** Accepted
- **Date:** 2026-05 (v0.1.0 → v0.1.1)

## Context

Slurmify's input was originally a single `gr.Audio(sources=["upload"])`
component. We wanted to support video files (mp4/mov/mkv/etc.) so users
could slurmify the audio track of their own video clips without first
extracting it in a separate tool.

We tried, in order, three approaches to make `gr.Audio` accept video
files:

1. **Add video extensions to `SUPPORTED_EXTS`.** No effect — the
   validation that fired wasn't ours.
2. **JS strip the `accept` attribute on the file input.** Stripped the
   browser's file-picker filter, but the upload still failed with
   `Invalid file type only audio/aac,audio/midi,audio/mpeg,...`.
3. **Add a second `gr.File` component below `gr.Audio` for videos
   only.** Worked technically but caused user confusion — the audio
   drop zone is bigger and labeled "Drop Audio Here", so users dropped
   videos there and hit the same error.

The root finding: **`gr.Audio` validates file MIME type
server-side**. There's no parameter on the component to override this
list; it's hardcoded to the audio MIME types. JS-level workarounds
that strip the `accept` attribute only affect the browser file picker
and are bypassed when files are dropped or selected programmatically
— the server still rejects.

## Decision

**Replace the input `gr.Audio` upload role with a `gr.File(file_types=
None)` as the single, primary drop target.** The `gr.Audio` component
is kept but starts `visible=False`; a change handler on the `gr.File`
routes the upload:

- If the file extension matches a known audio container (`_AUDIO_EXTS`
  set), the path is passed through directly to `gr.Audio.value` and
  the component becomes visible.
- If the extension is anything else (video container, other media),
  ffmpeg extracts the audio track to a session-temp `.wav` and the
  extracted path is fed to `gr.Audio`.

```python
# In build_ui()
media_file_in = gr.File(
    label="🎵📹 drop ANY audio or video file here",
    file_count="single",
    type="filepath",
    file_types=None,  # accept ANY file
    elem_id="slurm-media-file",
    elem_classes=["slurm-media-file"],
)
audio_in = gr.Audio(
    label="input audio",
    type="filepath",
    sources=["upload"],
    elem_classes=["slurm-audio"],
    visible=False,  # only appears after upload handler populates it
)

def _route_upload(media_path):
    if not media_path:
        return gr.update(value=None, visible=False)
    src = media_path if isinstance(media_path, str) \
          else getattr(media_path, "name", str(media_path))
    ext = Path(src).suffix.lower()
    if ext in _AUDIO_EXTS:
        return gr.update(value=src, visible=True)
    # Non-audio → ffmpeg extract
    out_path = _new_temp_path(suffix=".wav", prefix="extracted_")
    subprocess.run([ffmpeg_exe, "-y", "-i", src,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "44100", "-ac", "2", out_path],
                   check=True, capture_output=True)
    return gr.update(value=out_path, visible=True)

media_file_in.change(fn=_route_upload, inputs=media_file_in,
                     outputs=audio_in)
```

## Consequences

**Wins**

- **One drop zone, no confusion.** Users can't drop on the wrong target.
- **Any container Just Works** — mp3, wav, flac, mp4, mov, mkv, webm,
  wmv, flv, etc. ffmpeg handles whatever it can demux.
- **Audio files skip ffmpeg entirely.** No quality loss, no extra
  encode time on the common case.
- **`audio_in` retains its full waveform + transport behavior** once
  populated. The visible-toggle pattern means the page doesn't show
  an empty audio component before any file is loaded.

**Costs**

- **Two-step UX:** drop file → wait briefly while extraction completes
  → audio_in appears. For audio files this is essentially instant; for
  long videos the ffmpeg pass can take a few seconds.
- **`gr.File` doesn't show a waveform** in its own UI — the file is
  represented as a filename with size. The waveform appears in the
  separate `audio_in` component below it. Two-component visual.
- **Lost feature: drag-drop with immediate audio playback in the same
  zone.** Now requires the round-trip through the change handler
  before the player appears.

## Risks

- **Future Gradio releases might change `gr.File`'s behavior** — e.g.
  add MIME validation or change `file_types=None` semantics. If that
  happens, fallback options:
  1. Replace `gr.File` with a `gr.HTML` block containing a raw
     `<input type="file">` and read the file via JS → `fetch` POST to
     a custom endpoint mounted on Gradio's underlying FastAPI app.
  2. Use a Gradio `gr.Image` or `gr.Video` component (which has its
     own MIME list that includes video) and route appropriately.
- **`_AUDIO_EXTS` set must stay in sync with what librosa+audioread
  can actually load directly** — wrong-classifying an extension will
  cause librosa to fail later in the pipeline rather than gracefully
  routing to ffmpeg first. The set is conservative (well-known audio
  containers only); anything ambiguous defaults to ffmpeg.

## See also

- `app.py` `_route_upload` and `media_file_in.change(...)` wiring
- `_new_temp_path` for the session-scoped temp file the extracted
  WAV lives in (cleaned up on quit per ADR-0011)
- `_AUDIO_EXTS` set near the top of `build_ui()`'s event-handler block
