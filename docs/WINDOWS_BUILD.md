# Building Slurmify for Windows

> **Goal of this doc:** get a working Windows installer of SIENA Slurmer
> into Bob's hands as quickly and reliably as possible, without
> compromising the work we've done on the macOS pipeline.

---

## TL;DR

- **PyInstaller cannot cross-compile.** A Windows-runnable sidecar binary
  has to be built on Windows. There is no Mac-side workaround.
- **Tauri 2's MSI bundler is broken when `externalBin` is configured**
  ([tauri#14681](https://github.com/tauri-apps/tauri/issues/14681)).
  The Slurmify build uses externalBin (the PyInstaller sidecar), so
  **NSIS is the only viable installer format** for now. NSIS produces
  a `<app>-<version>-setup.exe` that's just as good as MSI for ad-hoc
  distribution.
- **Two paths to a working build**, recommended in this order:
  1. **GitHub Actions on `windows-latest`** — no Windows machine needed
     anywhere; commit + push, watch the workflow, download the
     installer. Recommended for one-off Bob testing.
  2. **A Windows machine (or VM on the Mac)** — Parallels / UTM /
     a borrowed laptop. Higher one-time setup cost, but useful
     long-term if Windows becomes a supported target.
- **Code signing is deferred.** The first build for Bob is unsigned;
  he sees a Microsoft SmartScreen warning on first launch and clicks
  "More info → Run anyway" once. Same posture as the macOS
  Gatekeeper-bypass story before we landed Apple Developer ID
  signing in v0.2.1.

---

## Why this is harder than macOS was

The macOS build (`scripts/build-dmg.sh`) runs on the host where the
.app is shipping. Mac → Mac. PyInstaller produces an arm64 binary,
Tauri produces an arm64 .app, both run on Apple Silicon Macs.

For Windows we need:
- A **Windows host** running the build (PyInstaller doesn't cross-compile).
- A **Windows-native ffmpeg.exe and rubberband.exe** bundled into the
  sidecar (we can't reuse the Mac binaries the existing spec finds via
  `brew`).
- A **Windows installer format** that works with externalBin (NSIS,
  not MSI).
- Optionally: an **Authenticode code-signing certificate** to skip
  SmartScreen friction (deferred for the first Bob round).

The good news: most of the v0.2.0 codebase was already written
cross-platform-ish. `slurmcore.py` and `slurmio.py` use `pathlib` and
`os.pathsep`. `server.py`'s `_MEIPASS` PATH bootstrap uses
`os.pathsep` (which is `;` on Windows, `:` on Unix). The Tauri shell's
discovery-file lookup uses `std::env::temp_dir()` which resolves
correctly on Windows. The only macOS-specific code in the runtime is
the entitlements file (Tauri ignores it on Windows) and the Finder
"reveal in Finder" command (the Rust handler can be Windows-extended
later, but the existing code path is non-blocking — the rest of the
app still works).

---

## Decision log

The following decisions were made up front to keep the first build
reachable. Each is reversible later.

### Installer format: **NSIS**, not MSI

NSIS is the de facto standard for "drag-and-drop simple installer for
a Windows desktop app." Tauri 2 generates a working NSIS installer
out of the box. The MSI bundler is currently broken with externalBin
(tauri#14681) and we'd hit it immediately. NSIS produces a single
`-setup.exe` file that's smaller and easier for Bob to download than
an MSI anyway.

### Build host: **GitHub Actions first, local Windows VM if needed**

GitHub Actions has a free `windows-latest` runner that comes with
Rust, Node, Python, and Visual Studio Build Tools pre-installed.
We push, the runner builds, the workflow uploads the installer as
an artifact, we download it and send to Bob. Total wall-clock time:
under 10 minutes from `git push` to "send Bob a download link."

If GitHub Actions becomes a bottleneck (private repo with limited
Actions minutes, frequent iterations, etc.), Path B documents how
to set up a local Windows build environment.

### Code signing: **deferred** to a follow-up

Authenticode certificates from Sectigo / DigiCert / SSL.com cost
~$200–700/year (OV vs. EV), and EV requires a hardware token.
SmartScreen reputation builds over time, so even an EV-signed
*new-publisher* binary still triggers warnings for a few weeks.
For Bob — one tester, one machine — clicking through SmartScreen
once is fine. Note in `docs/TESTER_README_WINDOWS.md` (created
alongside this plan) tells him exactly what to expect.

### Architecture: **x86_64 only, for now**

Bob's machine is x86_64. ARM64 Windows (the new Surface Pro X
family, Snapdragon X laptops) is a small minority. Building for
`x86_64-pc-windows-msvc` covers ~99% of Windows users including
Bob. Adding `aarch64-pc-windows-msvc` later is a parallel
PyInstaller build + a parallel Tauri build, fully additive.

### Versioning: **same v0.2.x line, no Windows-specific bump**

The code is the same. The Windows installer for `v0.2.1` is the
same v0.2.1 you ship on macOS. If the Windows build reveals a bug
that needs a Windows-specific fix (e.g., a path-handling glitch),
we bump to v0.2.2 for everyone.

---

## Path A — GitHub Actions (recommended for first run)

### Prereqs

- The Slurmify repo is in a GitHub remote (which it is — `origin/main`).
- Your GitHub account has Actions enabled (it does by default).
- For a **private** repo, your free monthly Actions minutes cover
  Windows builds (Windows minutes count 2× — so a 7-minute build is
  14 minutes off your quota; the standard free tier of 2,000
  min/month is plenty for development).

### Step 1 — add the workflow file

Create `.github/workflows/windows-build.yml` in the repo (template at
the bottom of this doc and committed alongside this plan). Push it.

### Step 2 — trigger the build

Either:

- **Push a tag** named like `v0.2.1-win` — the workflow listens for
  tags matching `v*-win`. Recommended for "I want a build now":

  ```bash
  git tag v0.2.1-win
  git push origin v0.2.1-win
  ```

- **Manual dispatch** from the GitHub Actions tab (Run workflow…).
  Useful for one-off rebuilds without polluting the tag list.

### Step 3 — download the installer

When the workflow finishes (typically 8–12 minutes — Rust compile is
the slow step on a cold cache), open the run page on github.com.
Scroll to the bottom — there's an **Artifacts** section with a
"slurmify-windows-installer" zip. Download, unzip, find:

```
SIENA Slurmer_0.2.1_x64-setup.exe
```

That's the file Bob needs.

### Step 4 — send to Bob

Email/Drive/Dropbox the `.exe` to Bob along with the contents of
`docs/TESTER_README_WINDOWS.md` (or just paste the SmartScreen
bypass instructions in the message). Bob double-clicks, gets the
SmartScreen warning, clicks "More info" → "Run anyway", goes
through the standard NSIS installer wizard, launches Slurmify
from the Start menu.

### Step 5 — when Bob reports issues

Check the GitHub Actions log first — if anything went wrong on the
build side, the log shows it. For runtime issues, ask Bob to:

- Open `Event Viewer` (Win+R → `eventvwr`) and look at Windows Logs →
  Application for crash entries.
- Open the sidecar log: it lives at
  `%LOCALAPPDATA%\com.subvoyant.siena.slurmer\slurmify-backend.log`
  if we add file logging (deferred — for now the sidecar's stderr
  goes to the Tauri shell's stderr, which Windows discards by default
  because Tauri runs as a GUI app).
  - Workaround for log-capture in this first build: ask Bob to run
    the .exe from a `cmd` window:
    ```
    "%LOCALAPPDATA%\Programs\SIENA Slurmer\siena-slurmer.exe" 2> %TEMP%\slurmify.log
    ```
    Then send us `%TEMP%\slurmify.log`.

---

## Path B — local Windows machine (or VM on the Mac)

Use this when the GitHub Actions path becomes too slow to iterate on
(e.g., Bob reports a Windows-only bug and you're rebuilding 5×/day).

### B.1 Choosing a host

| Option | Setup time | Cost | Notes |
|---|---|---|---|
| **Borrowed Windows laptop** | minutes | $0 | Fastest if you have access to one. |
| **Parallels Desktop on Apple Silicon** | ~30 min | $99/yr | Smoothest VM experience on M-series Macs. Supports Windows 11 ARM64. PyInstaller's Python wheels and Visual Studio Build Tools work on ARM64 Windows but are less battle-tested than x86_64. Recommend running a **Windows 11 x86_64** VM (Parallels can do this on M-series via JIT translation — slower, but compatible with the x86_64 wheels we need). |
| **UTM (free) on Apple Silicon** | ~1 hour | $0 | Open-source. Slower than Parallels for x86_64 emulation. Doable. |
| **VMware Fusion** | ~30 min | Free for personal use as of 2024 | Comparable to Parallels, somewhat less polished. |
| **Cloud Windows VM** | ~10 min | $0.10–0.50/hr | Azure/AWS Windows 11 instance. Good for one-shot builds; expensive if left running. |

For a first-time Windows build: Parallels or a borrowed laptop are
the easiest. UTM works but expect every step to be slower.

### B.2 Toolchain installation (on the Windows host)

Run as Administrator in PowerShell. Each line below has been tested
on a clean Windows 11 install.

```powershell
# 1. Chocolatey package manager (one-liner from chocolatey.org)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol =
    [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString(
    'https://community.chocolatey.org/install.ps1'))

# 2. Visual Studio Build Tools (Rust needs MSVC linker)
choco install -y visualstudio2022buildtools `
    --package-parameters "--add Microsoft.VisualStudio.Workload.VCTools `
    --includeRecommended"

# 3. Rust toolchain
choco install -y rustup.install
rustup default stable
rustup target add x86_64-pc-windows-msvc

# 4. Node + pnpm
choco install -y nodejs-lts
corepack enable
corepack prepare pnpm@latest --activate

# 5. Python 3.12
choco install -y python --version=3.12.6
# (if pip is missing: python -m ensurepip --upgrade)

# 6. ffmpeg + rubberband — the runtime CLIs the sidecar shells out to
choco install -y ffmpeg
choco install -y rubberband-cli

# 7. Git (if not already installed)
choco install -y git
```

After all the above, **close and reopen PowerShell** so the new PATH
entries take effect.

### B.3 One-time repo setup on the Windows host

```powershell
git clone https://github.com/<your-org>/slurmify
cd slurmify

# Backend Python venv (mirrors src-python/.venv on Mac)
cd src-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ..

# Frontend dependencies
pnpm install

# Sanity check — the sidecar entry runs in dev mode:
cd src-python
python server.py
# (you should see a `slurmify_ready` JSON line — Ctrl-C to stop)
cd ..
```

### B.4 Build for Windows

```powershell
.\scripts\build-windows.ps1
```

The script (created alongside this plan):
1. Activates the venv.
2. Builds the PyInstaller sidecar to
   `src-tauri\binaries\slurmify-backend-x86_64-pc-windows-msvc.exe`.
3. Runs `pnpm tauri build --bundles nsis` (NSIS only — explicitly
   skips MSI to dodge tauri#14681).
4. Reports the produced `-setup.exe` path.

Total time on a moderately fast Windows machine: ~5–8 minutes
(longer the first time because of the Rust compile cache).

Output:
```
src-tauri\target\release\bundle\nsis\SIENA Slurmer_0.2.1_x64-setup.exe
```

### B.5 Distribute

Same as Path A step 4. Send the `.exe` to Bob.

---

## Code adaptations

The Slurmify codebase needs a few small changes to handle Windows
cleanly. These are all additive — they don't break the macOS build.

### `src-python/slurmify-backend.spec`

Already cross-platform-friendly via `shutil.which()` — on Windows
it finds `ffmpeg.exe` and `rubberband.exe` automatically. The spec's
`binaries.append((path, "."))` also works on Windows (the dst path
`"."` means "bundle root" on every platform). **No change needed.**

The build-time guards (`raise SystemExit` if ffmpeg/rubberband is
missing) work identically — on Windows the error message tells the
user to `choco install ffmpeg` instead of `brew install ffmpeg`,
but otherwise behaves the same. Optional polish: detect platform
and print platform-appropriate install hints.

### `src-tauri/tauri.conf.json`

The `bundle.targets` field is currently `["dmg", "app"]` (macOS-only).
For a cross-platform config, change to:

```json
"bundle": {
  ...
  "targets": ["dmg", "app", "nsis"],
  ...
}
```

Tauri silently skips targets it can't build on the current platform,
so this doesn't break the macOS build (DMG + app on macOS) but
enables NSIS on Windows. The `bundle.macOS` block is also silently
ignored on Windows.

### `src-tauri/Cargo.toml`

Already cross-platform — no change needed. The `tauri-plugin-shell`,
`tauri-plugin-fs`, and `tauri-plugin-dialog` crates have Windows
implementations.

### `src-tauri/src/lib.rs`

The `reveal_in_finder` Tauri command is macOS-specific (it shells
out to `open -R`). On Windows it would silently no-op or fail. For
Bob's first build this is fine — the equivalent feature is "open
File Explorer at this path", and we can implement it in a follow-up.

### `src-python/server.py`

The `_MEIPASS` PATH bootstrap uses `os.pathsep`, which is `;` on
Windows and `:` on Unix — already correct.

The discovery-file path uses `tempfile.gettempdir()`, which on
Windows resolves to `C:\Users\<user>\AppData\Local\Temp`. The Tauri
Rust shell's `std::env::temp_dir()` resolves to the same path on
Windows. **Confirmed cross-platform.**

### `scripts/`

Two new files (created alongside this plan):
- `scripts/build-sidecar.ps1` — PowerShell mirror of `build-sidecar.sh`.
- `scripts/build-windows.ps1` — PowerShell mirror of `build-dmg.sh`,
  minus the codesign/notarization blocks (those are macOS-specific).

The existing bash scripts are unchanged. macOS users keep using
`build-dmg.sh`; Windows users run `build-windows.ps1`.

### `.github/workflows/windows-build.yml`

The CI workflow file (created alongside this plan; see template
below). Triggered on `v*-win` tags or manual dispatch. Builds
the sidecar + Tauri app on `windows-latest`, uploads the
`-setup.exe` as a build artifact.

---

## Distributing to Bob

### What Bob will see on first launch

1. He downloads `SIENA Slurmer_0.2.1_x64-setup.exe`.
2. He double-clicks. Windows shows a **SmartScreen** dialog:

   > **Windows protected your PC**
   > Microsoft Defender SmartScreen prevented an unrecognized app
   > from starting. Running this app might put your PC at risk.
   > Don't run / More info

3. He clicks **More info**. The dialog expands to show:

   > Publisher: Unknown publisher
   > [Run anyway]

4. He clicks **Run anyway**. The NSIS installer wizard opens.
   Standard Next → Next → Install flow.
5. The installer puts the app in
   `%LOCALAPPDATA%\Programs\SIENA Slurmer\` (no admin rights
   required) and creates Start Menu + Desktop shortcuts.
6. He launches from Start Menu. The app opens. Same UI as macOS,
   minus the Reveal-in-Finder button (which is macOS-only — see
   "Code adaptations" above).

### Bundle a `TESTER_README_WINDOWS.md` with the installer

Create `docs/TESTER_README_WINDOWS.md` (a Windows-specific spin on
the macOS tester README). Bullet points to include:

- The SmartScreen bypass click-through (steps 2–4 above), with a
  reassurance that the warning is normal for unsigned apps and
  doesn't mean the file is malicious.
- The install path (`%LOCALAPPDATA%\Programs\SIENA Slurmer\`) so
  Bob knows where to look if he wants to manually delete.
- How to capture sidecar logs if something misbehaves (the cmd
  redirection trick from Path A step 5).
- A note that Apple-Mac signing/notarization on Windows means
  buying an Authenticode cert and is a separate workstream — same
  framing as the v0.2.0 → v0.2.1 macOS arc.

A draft of this is committed at `docs/TESTER_README_WINDOWS.md`
alongside the build scripts.

---

## What's deferred

These are explicit non-goals for Bob's first build, with notes for
the future:

- **Authenticode signing.** Either OV cert via Sectigo (~$200/yr,
  ~3-week SmartScreen warm-up period before warnings ease) or EV
  cert (~$400+/yr, requires a hardware HSM token, immediate trust).
  Recommend EV when this becomes priority — the time saved on
  reputation building is worth the extra $200/yr.
- **Auto-updater.** Tauri 2 has an updater plugin that can pull
  from a JSON endpoint and verify ed25519 signatures. Deferred
  until we have more than one Windows user.
- **MSI installer.** Blocked on tauri#14681. NSIS is fine for
  ad-hoc distribution; MSI matters for enterprise IT environments
  (Group Policy deployment, etc.) which we don't need yet.
- **ARM64 Windows build.** Add `aarch64-pc-windows-msvc` to the
  Rust target list and run a parallel PyInstaller pass on an
  ARM64 Windows machine. Worth doing once we have a tester on
  Surface Pro X / Snapdragon X.
- **Reveal in File Explorer.** Implement a Windows branch of the
  `reveal_in_finder` Tauri command using `explorer.exe /select,<path>`.
  One-line patch in `src-tauri/src/lib.rs`.
- **Capture sidecar logs to a file.** Add a `logging` config in
  `server.py` that writes to
  `%LOCALAPPDATA%\com.subvoyant.siena.slurmer\slurmify-backend.log`
  on Windows and `~/Library/Logs/com.subvoyant.siena.slurmer/` on
  macOS. Without this, Tauri's stderr goes nowhere on Windows.

---

## Appendix A — `.github/workflows/windows-build.yml` template

(This is the workflow file that Path A pushes. It's also committed
to `.github/workflows/windows-build.yml` alongside this plan.)

```yaml
# .github/workflows/windows-build.yml
#
# Builds the Slurmify Windows installer on a GitHub-hosted
# windows-latest runner.  Triggered by tags matching `v*-win` (push
# `v0.2.1-win` to kick off a 0.2.1 Windows build) or by manual
# dispatch from the Actions tab.
#
# Output: a `slurmify-windows-installer` artifact attached to the
# workflow run, containing the NSIS -setup.exe.  Click the run on
# github.com → scroll to Artifacts → download.

name: Build Windows installer

on:
  push:
    tags:
      - "v*-win"
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Set up Node + pnpm
        uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: corepack enable && corepack prepare pnpm@latest --activate

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable
        with:
          targets: x86_64-pc-windows-msvc

      - name: Install ffmpeg + rubberband
        run: |
          choco install -y ffmpeg
          choco install -y rubberband-cli

      - name: Install backend Python deps
        working-directory: src-python
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Build sidecar
        run: powershell -ExecutionPolicy Bypass -File scripts\build-sidecar.ps1

      - name: Install frontend deps
        run: pnpm install

      - name: Build Tauri (NSIS only — MSI is blocked on tauri#14681)
        run: pnpm tauri build --bundles nsis

      - name: Upload installer artifact
        uses: actions/upload-artifact@v4
        with:
          name: slurmify-windows-installer
          path: src-tauri/target/release/bundle/nsis/*.exe
          retention-days: 14
```

---

## Appendix B — quick verification checklist after the build

Run these on Bob's machine (or your Windows host) after install:

```powershell
# App launched?  Check the process is running:
Get-Process | Where-Object { $_.Name -match "siena-slurmer|slurmify" }

# Sidecar reachable?  The discovery file should exist:
Test-Path "$env:TEMP\slurmify-backend.json"
Get-Content "$env:TEMP\slurmify-backend.json"
# Should print {"port":NNNNN,"pid":NNNN,...}

# Sidecar responding?
$port = (Get-Content "$env:TEMP\slurmify-backend.json" | ConvertFrom-Json).port
Invoke-RestMethod "http://127.0.0.1:$port/health"
# Should return @{ status="ok"; version="0.2.1"; ready=$true; tmp_dir="..." }

# ffmpeg + rubberband bundled?  Open Task Manager → Details, find
# slurmify-backend.exe, look at its loaded modules — should show
# the bundle's _MEI<hash> temp dir.  Or just drop a file in the
# UI and watch for the upload to succeed end-to-end.
```

If all four pass, the build is good. Send the `.exe` to Bob.

---

## Appendix C — common pitfalls

- **`rustc` not found during the Tauri build step.**
  PATH didn't refresh after rustup install. Close and reopen
  PowerShell, or `refreshenv` if Chocolatey is in PATH.

- **PyInstaller fails with `librosa`-related ImportError at
  runtime.** Some hidden imports librosa pulls in are different on
  Windows than on macOS. The current spec's `collect_submodules("librosa")`
  pass should cover this, but if a tester hits a missing-module
  error, add the specific module name to the `hidden` list and
  rebuild. Tauri-side rebuild is fast; only the PyInstaller pass
  is slow.

- **Tauri bundler error `failed to bundle project: error running
  light.exe`.** This is the MSI bundler failing — happens if you
  forget to pass `--bundles nsis`. The build script does this
  automatically. If you see this error, you're running
  `pnpm tauri build` without the flag.

- **NSIS installer crashes on launch.** Check Event Viewer →
  Windows Logs → Application for the entry point. Most common cause
  is a missing Visual C++ redistributable on the user's machine
  (not the build host) — Tauri's NSIS bundler should auto-install
  vcredist, but on very old Windows builds it sometimes doesn't.
  Manual fix: ship the user a vcredist installer alongside the
  Slurmify installer.

- **SmartScreen "Run anyway" button missing.** Some corporate
  Windows installs are configured to remove the bypass button via
  Group Policy. Bob isn't on a corporate-managed machine, but if
  this comes up later, the only path is: get the cert and notarize
  the binary, OR have IT whitelist the app.

---

## Appendix D — references

- [Tauri 2 Windows Installer guide](https://v2.tauri.app/distribute/windows-installer/)
- [tauri-apps/tauri#14681 — MSI bundling fails with externalBin on Windows](https://github.com/tauri-apps/tauri/issues/14681)
- [tauri-action — official GitHub Action for Tauri builds](https://github.com/tauri-apps/tauri-action)
- [PyInstaller — cross-compilation FAQ (not supported)](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-operating-systems)
- [Microsoft SmartScreen — How it works](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/)
- Slurmify ADR-0022 (Tauri 2 + React 19 migration)
- Slurmify ADR-0025 (Apple Developer ID signing — the equivalent
  workstream for Windows is the deferred Authenticode item above)

---

*Last updated: 2026-05-09 · Plan author: Slurmify maintainers · Targeting v0.2.1 Windows · Status: ready to execute Path A.*
