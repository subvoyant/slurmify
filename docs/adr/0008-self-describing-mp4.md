# ADR-0008: Embed slurm patch as JSON in the MP4 `description` atom

- **Status:** Accepted
- **Date:** 2026-05-04

## Context

When the user exports a YouTube MP4, they may want to:

1. Have YouTube's upload form pre-fill the title and description.
2. Reproduce the same slurm later — re-run the same audio with the
   same parameters and FX settings to make a v2.
3. Share a patch with someone else without sending a sidecar JSON
   file.

Standard MP4/iTunes-style metadata atoms (`title`, `artist`,
`description`, etc.) handle (1). For (2) and (3), the file needs to
be self-describing.

## Decision

**Write the slurm patch (every input parameter to `slurmify()` plus
every FX slider value) as a single-line JSON blob into the MP4's
`description` atom, prefixed by `PATCH=`.**

Schema (kept stable across versions; bump `version` field on
breaking changes):

```json
{
  "version": "0.1.6",
  "source":  "<filename or null>",
  "seed":    <int or null>,
  "core":    { "speed": ..., "resolution": ..., "envelope_ms": ..., ... },
  "fx":      { "dist_drive": ..., "ring_freq": ..., ... },
  "audio_source": "FX-burned output" | "slurm output",
  "rendered_at":  "<ISO-8601 UTC>"
}
```

The leading lines of `description` are human-readable prose
(`"Made with Subvoyant SIENA Slurmer · subvoyant.com"` plus a
short summary). YouTube uses those as the auto-filled description.
The `PATCH={...}` line at the bottom is for machines.

Source filename inclusion is **opt-in** via a checkbox in the export
panel, defaulted to off, so the patch JSON is anonymous unless the
user agrees to leak the original filename.

## Consequences

**Wins**

- Files are self-describing — no sidecar to lose.
- A future "Import patch from MP4" feature is trivial: read
  `description`, regex-extract `PATCH={...}`, `JSON.parse`, populate
  sliders.
- YouTube auto-fills title and description (genuinely useful, saves
  a step).
- Diffing patches is just `jq` on `description`.

**Costs**

- Description gets long (~500–800 bytes of JSON for a typical
  patch). Not visible to most users; ffprobe / mediainfo show it.
- We commit to schema stability. Breaking the shape requires either
  a `version` bump and a parser that handles both, or a separate
  custom atom.

## Privacy note

The `source` field can leak the user's library organization
(`taylor_swift_unreleased_demo.mp3`). Hence the opt-in checkbox.

## See also

- `app.py` `render_video()` — `patch` dict construction, `PATCH=`
  line in the description, the `metadata` dict passed to ffmpeg as
  `-metadata key=value`
- ADR-0006 — the loop MP4 / stream-copy work that made this export
  fast enough to use casually
