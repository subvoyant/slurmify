# SIENA Slurmer v0.2.1 — Tester Notes

Hi Max — thanks for testing. This is the **v0.2.1** polish build of the new Tauri/React UI you saw in v0.2.0. Same shape, fewer rough edges.

---

## What's new in 0.2.1

The first **signed + notarized** Slurmify build. Plus several rough-edge fixes that came out of the v0.2.0 tester round:

- **Signed + notarized DMG.** Apple's Developer ID signature + notarization ticket are now stapled onto both the .app and the DMG, so Gatekeeper accepts the app on a clean Mac with no terminal commands and no right-click → Open dance. Just double-click and it opens.
- **YouTube render bakes FX by default.** Dialing up FX and clicking "render YouTube MP4" now embeds those effects in the output without making you click "burn FX" first. The FX chain is auto-burned right before the video render every time, so the export always reflects your current knob state. If you specifically want a clean dry render, the audio-source picker has a "clean slurm (dry)" opt-out.
- **Working video render.** v0.2.0's render-YouTube-MP4 button died with `FileNotFoundError: Missing animation loop` — the loop animation MP4 wasn't bundled into the .app. Fixed; renders work end-to-end now.
- **Better diagnostics.** If something fails at upload, burn-FX, or render-video, the error message in the UI now includes specifics (HTTP status, request state) instead of a bare "upload failed". Sidecar logs in `Console.app` (filter to `slurmify-backend`) carry detailed per-request lines for triage.
- **Sticky top bar.** The preset picker and the utility actions (randomize, reveal temp, tooltips, easter eggs, quit) merged into one compact bar that stays pinned at the top while you scroll through the rack modules. Less vertical chrome to hunt past.

The DSP engine is still the same one you know from 0.1.6 — no audio-quality changes.

---

## What's new in 0.2.0 (recap, in case you skipped to 0.2.1)

A from-scratch UI rebuild. The DSP engine is the same one you know from 0.1.6 — stereo end-to-end, the four time controls in ms or notes, beat mask chip strip, MAX RANDOM with Max's hover gif, all the easter eggs. What changed is everything around it:

- **Native macOS window.** No browser tab, no `127.0.0.1:7860` to remember. Double-click the app, the window appears.
- **Tauri 2 + React 19 frontend.** Built on a proper UI toolkit instead of a Gradio + injected-JS hack. Means controls feel responsive, animations are smooth, and the app survives things that broke Gradio (window resizing, multiple monitors, dark/light mode flips).
- **Python sidecar process.** All the slurmcore DSP code from 0.1.6 (slicing, stretching, FX, video export) runs in a separate Python process the app launches at startup. Same algorithms, same audio quality — just isolated from the UI so a slow slurmify can't freeze the window. (See ADR-0022 if you're curious.)
- **No port collision.** The sidecar picks a random free port at launch, so you can run multiple copies, or run alongside whatever else has 7860 grabbed.

---

## 1. Install

1. Double-click **`SIENA Slurmer 0.2.1.dmg`**.
2. Drag **SIENA Slurmer 0.2.1.app** into your **Applications** folder.
3. Eject the DMG.

The DMG also contains:
- **Read Me — Tester Notes.md** — this file, in case you want to refer back without poking inside the .app.
- **LICENSE** — GPL-3.0 plus third-party notices for rubberband, ffmpeg, librosa, etc.

---

## 2. First launch

The DMG and the .app inside it are **signed with our Apple Developer ID and notarized by Apple** (Subvoyant team), so Gatekeeper accepts the app on a clean Mac with no extra steps. Just double-click the app from your Applications folder — the window opens.

### If you're upgrading from an earlier 0.2.0 build that wasn't notarized

If you previously installed an unsigned build of SIENA Slurmer 0.2.0 and saw the "is damaged" dialog, drag the OLD copy to the Trash before installing this one. macOS sometimes caches a "this app is bad" decision against the bundle ID — moving the old copy out clears it. Then drag the new .app into Applications and double-click as usual.

### If you DO see a Gatekeeper dialog

That would mean either (a) you got an unofficial build, or (b) something went wrong with our notarization upload. Either way, please screenshot the dialog and send it back — we'll dig in.

---

## 3. Use it

Drop an audio file (mp3, wav, m4a, flac, aiff, ogg) onto the dropzone and start tweaking. Hover any control to see what it does.

The app is fully **offline** — your audio never leaves your machine. All session output files live in a temp folder that's wiped when you quit; if you want to keep something, use the **save…** button next to the output waveform or **render YouTube MP4** in the Video Export rack.

The 📁 **reveal temp** button in the top utility bar opens the session temp folder in Finder — useful for grabbing intermediate files before they're auto-cleaned.

---

## What I want to know

When you find bugs, anything you'd like to flag, send a screenshot + a one-line description. Helpful details:

- Which slurm preset / settings produced the issue
- Was a slurmify job running, or was it idle?
- Was the FX rack engaged, or just dry slurm?
- Anything that worked in 0.1.6 and is now broken in 0.2.0 (this is a high-priority class of regression — the rewrite is supposed to be a UI swap, not a behaviour change)

Have fun.

— Subvoyant
