# SIENA Slurmer for Windows — Tester Notes

Hi Bob — thanks for testing the Windows version.

This is SIENA Slurmer **0.2.3** for Windows — same desktop app the Mac team has been testing, packaged for Windows instead of macOS. The FX rack got a significant expansion in this release; see "What's new in 0.2.3" below.

---

## What's new in 0.2.3

The FX rack has three new effects and a real-time pitch shifter:

- **PITCH module** — new effect with SEMITONES (±24) and CENTS (±100) knobs plus a wet/dry MIX. Twist the knob, hear the pitch change immediately (~20 ms latency); burns into the YouTube render too at offline phase-vocoder quality.
- **Tremolo, auto-panner, and reverb now bake into the burn / YouTube render.** Previously these only worked in live preview and silently disappeared from the rendered output. Now what you hear is what you export.
- **Beat-mode toggles on every rate/time FX param** — Hz ⇄ ♪ on ring sweep, panner sweep, and phaser rate, matching what tremolo and delay already had. Lock LFO rates to note values at the detected BPM.
- **Compressed FX rack layout** — PANNER reorganized as a 2×2 grid + wave selector; DELAY and REVERB stacked Olympic-rings style; PITCH module slots in between PANNER and REVERB. Same panel height as v0.2.1, just denser.

The audio engine (slicing, stretching, the original four FX) is unchanged from what you've been testing on the Mac side.

---

## What you got

A single file: **`SIENA Slurmer_0.2.3_x64-setup.exe`** — that's a standard Windows installer. Run it, follow the wizard, you're set. (If you have an older v0.2.1 install, the new installer replaces it in-place; no need to uninstall first thanks to the NSIS pre-install hook that kills the running app.)

---

## 1. Install

1. Find **`SIENA Slurmer_0.2.3_x64-setup.exe`** in your Downloads folder.
2. Double-click it.

## 2. The "Windows protected your PC" dialog

This is the part that's going to look scary. **It is not actually scary.** Here's what's happening:

When Microsoft Windows hasn't seen an app before — and we're a tiny indie tool, so it hasn't — it pops up a dark blue dialog that says:

> **Windows protected your PC**
> Microsoft Defender SmartScreen prevented an unrecognized app from starting. Running this app might put your PC at risk.

This is the same warning Windows shows for **every** new indie app on its first launch on a given Mac. It does NOT mean we found a virus. It means the app doesn't have an "Authenticode signature" (the Windows equivalent of an Apple Developer ID, which we have on the Mac side as of v0.2.1 but not yet on Windows — adding it is a separate ~$200/year workstream we'll get to before public release).

To bypass:

1. In the SmartScreen dialog, click the small **"More info"** link near the top of the dialog. The dialog expands.
2. The publisher will read **"Unknown publisher"** and a **"Run anyway"** button appears at the bottom.
3. Click **"Run anyway"**.

That's it. You'll only see this dialog the first time. Future double-clicks of the installed app open it normally without any warning.

## 3. Run through the installer wizard

Standard NSIS installer flow:

- **License agreement.** GPL-3.0 (the same license slurmcore uses). Click "I Agree."
- **Choose install location.** Default is `C:\Users\<you>\AppData\Local\Programs\SIENA Slurmer\`. No admin rights required — the installer doesn't touch `Program Files` or the registry beyond a Start Menu / Desktop shortcut. Default is fine; click "Install."
- **Finish.** A "Run SIENA Slurmer" checkbox is on by default. Leave it checked, click "Finish," and the app launches.

## 4. Use it

Drop an audio file (mp3, wav, m4a, flac, aiff, ogg) onto the dropzone and start tweaking. Hover any control to see what it does. Same UI, same workflow, same sound as the Mac version.

The app is fully **offline** — your audio never leaves your machine. All session output files live in a temp folder that's wiped when you quit; if you want to keep something, click the **save…** button next to the output waveform or hit **render YouTube MP4** in the Video Export rack.

The Mac version has a "📁 reveal temp" button that opens the temp folder in Finder. On Windows that button isn't wired up yet (Windows uses File Explorer, different command) — for now, the temp folder lives at `%TEMP%\slurmify-session-<random>\` if you ever need to grab something manually. Type `%TEMP%` in the Windows + R dialog or any Explorer address bar and look for a `slurmify-session-*` folder.

---

## What I want to know

Send a screenshot + a one-line description for anything that bugs you or breaks. Especially helpful:

- Anything that visibly looks worse on Windows than it did on the Mac builds you've seen — fonts, spacing, colors, dialog rendering, any of it. Some of this is "Windows just renders fonts differently" which is fine, but if a UI element is *broken* on Windows we want to know.
- Anything that worked on the Mac side and is broken/missing on Windows. (The reveal-temp button is a known one — anything else is unexpected.)
- Crashes or hangs. If the app crashes, see "Crash logs" below.

Send it to: software@subvoyant.com or paste in the team chat.

---

## Crash logs (if needed)

If the app crashes or silently fails to launch, we'd like to see what the Python sidecar said before it died. The easiest way to capture this:

1. Open the **Command Prompt** (Win + R, type `cmd`, Enter).
2. Run:
   ```
   "%LOCALAPPDATA%\Programs\SIENA Slurmer\siena-slurmer.exe" 2> %TEMP%\slurmify.log
   ```
3. Reproduce the crash.
4. Send us the contents of `%TEMP%\slurmify.log` (just type `notepad %TEMP%\slurmify.log` to open it).

(In v0.2.2 we'll wire up proper log-file capture so this manual redirection won't be needed.)

---

## Uninstall

The installer registers SIENA Slurmer as a normal Windows app, so there are three ways to remove it — pick whichever is easiest:

**Option 1 — Start Menu (fastest).** Open the Start Menu, type "SIENA Slurmer," right-click the app icon, and choose **"Uninstall."** Windows opens "Installed apps"; click the **"…"** next to SIENA Slurmer, then **"Uninstall."** Confirm and it's gone in a few seconds.

**Option 2 — Settings.** Open **Settings → Apps → Installed apps**, scroll to "SIENA Slurmer," click the **"…"** menu, click **"Uninstall."**

**Option 3 — Run the uninstaller directly.** The installer drops an `uninstall.exe` next to the app binary at `%LOCALAPPDATA%\SIENA Slurmer\uninstall.exe`. Double-click it from File Explorer, or paste that path into Win + R and hit Enter.

All three routes do the same thing: remove the install folder, the Start Menu shortcut, and the registry entry under HKCU. The installer does NOT require admin rights (per-user install mode), so the uninstaller doesn't either — no UAC prompt.

**What the uninstaller leaves behind.** Session temp files under `%TEMP%\slurmify-session-*\` are NOT touched (they're transient by design — Slurmify wipes them on quit; if Slurmify ever crashed mid-session there may be a few lingering folders Windows cleans up on its own schedule). If you want to scrub them manually: paste `%TEMP%` into File Explorer's address bar and delete anything matching `slurmify-session-*`.

---

Thanks Bob. Have fun.

— Subvoyant
