# ──────────────────────────────────────────────────────────────────────
# scripts/build-sidecar.ps1 — Build the PyInstaller sidecar for Windows
# ──────────────────────────────────────────────────────────────────────
#
# PowerShell mirror of scripts/build-sidecar.sh.  Same intent: produce a
# standalone Python+FastAPI+DSP bundle at
#   src-tauri\binaries\slurmify-backend-<rust-triple>.exe
# which Tauri's externalBin convention copies into the bundled .exe at
# `pnpm tauri build` time.
#
# PyInstaller does not cross-compile (see docs/WINDOWS_BUILD.md); this
# script is intended to run ON Windows, never on macOS.  It refuses to
# run on a non-Windows host as a guard.
#
# Prereqs (one-time on the build host):
#   - Python 3.11+ with src-python deps installed (`pip install -e ".[dev]"`)
#   - Rust toolchain with x86_64-pc-windows-msvc target
#   - ffmpeg.exe + rubberband.exe on PATH (see docs/WINDOWS_BUILD.md
#     §B.2 — `choco install ffmpeg rubberband-cli`)
#
# Usage (from the repo root):
#     .\scripts\build-sidecar.ps1
#
# Or override the Python interpreter:
#     $env:PY = "C:\path\to\venv\Scripts\python.exe"
#     .\scripts\build-sidecar.ps1
# ──────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

# Refuse to run on a non-Windows host — produces a confusing
# "PyInstaller built for the wrong OS" failure if it runs on macOS
# or Linux by accident.
if (-not $IsWindows -and ($PSVersionTable.PSEdition -ne "Desktop")) {
    Write-Error "[build-sidecar] This script is for Windows only. Use scripts/build-sidecar.sh on macOS/Linux."
}

# ── Paths ──────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..")

Set-Location (Join-Path $RepoRoot "src-python")

# ── Python interpreter ────────────────────────────────────────────────
# Default: the venv-activated `python` on PATH.  Override with $env:PY.
$Py = if ($env:PY) { $env:PY } else { "python" }

# ── Sanity checks ──────────────────────────────────────────────────────
$PyVersion = & $Py --version
$PyPath    = (Get-Command $Py).Source
Write-Host "[build-sidecar] Using $PyVersion at $PyPath"

& $Py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error @"
[build-sidecar] ERROR: PyInstaller not installed in this Python.
                 Install with: $Py -m pip install pyinstaller
                 Or: $Py -m pip install -e "$RepoRoot\src-python[dev]"
"@
}

& $Py -c "import librosa, soundfile, fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error @"
[build-sidecar] ERROR: backend deps missing in this Python.
                 Install with: $Py -m pip install -e "$RepoRoot\src-python[dev]"
"@
}

# ── Verify ffmpeg + rubberband are on PATH at BUILD time ──────────────
# The PyInstaller spec hard-fails if these are missing (per ADR-0023).
# We pre-check here for a friendlier error message.
#
# NOTE: rubberband is NOT available on Chocolatey (the `rubberband-cli`
# package does not exist; we discovered this the hard way when the first
# CI build failed at the choco step).  The official Windows binary is
# downloaded from Breakfast Quay — see docs/WINDOWS_BUILD.md §B.2 for
# the install snippet.
foreach ($cli in @("ffmpeg", "rubberband")) {
    $found = Get-Command $cli -ErrorAction SilentlyContinue
    if (-not $found) {
        if ($cli -eq "rubberband") {
            # Two-line plain string instead of a here-string because here-
            # strings with backtick-escaped variables hit a PowerShell
            # parser quirk that broke the v0.2.1-win-2 CI build.  Keep
            # this simple — the docs have the full install snippet.
            Write-Error "[build-sidecar] ERROR: rubberband.exe not found on PATH. rubberband is NOT a Chocolatey package; install the Breakfast Quay Windows binary per docs/WINDOWS_BUILD.md section B.2."
        } else {
            Write-Error "[build-sidecar] ERROR: $cli not found on PATH. Install with: choco install $cli"
        }
    } else {
        Write-Host "[build-sidecar] $cli at $($found.Source)"
    }
}

# ── Host triple — what Tauri's externalBin resolver expects ────────────
# Tauri picks the binary whose filename ends with the rust-target host
# triple of the build machine.  We let `rustc` resolve it
# authoritatively rather than guessing from $env:PROCESSOR_ARCHITECTURE.
$rustcOutput = & rustc -vV
if ($LASTEXITCODE -ne 0) {
    Write-Error "[build-sidecar] ERROR: rustc not found. Install via rustup (https://rustup.rs)."
}
$HostTriple = ($rustcOutput | Select-String "^host:" | ForEach-Object {
    $_.Line -replace "^host:\s*", ""
}) | Select-Object -First 1
if (-not $HostTriple) {
    Write-Error "[build-sidecar] ERROR: could not parse host triple from rustc -vV."
}
Write-Host "[build-sidecar] Host triple: $HostTriple"

# ── Clean prior build outputs ─────────────────────────────────────────
# Same posture as the bash version — nuke build/dist/ from src-python
# AND any prior bundle binaries from src-tauri/binaries/ so a stale
# .pyc or out-of-date binary can't sneak through.
foreach ($p in @(
    "$RepoRoot\src-python\build",
    "$RepoRoot\src-python\dist",
    "$RepoRoot\src-tauri\binaries\slurmify-backend-$HostTriple",
    "$RepoRoot\src-tauri\binaries\slurmify-backend-$HostTriple.exe"
)) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "[build-sidecar] cleaned $p"
    }
}

# ── Build ──────────────────────────────────────────────────────────────
Write-Host "[build-sidecar] Running PyInstaller (onefile)..."
& $Py -m PyInstaller --noconfirm slurmify-backend.spec
if ($LASTEXITCODE -ne 0) {
    Write-Error "[build-sidecar] PyInstaller failed."
}

# PyInstaller writes the onefile to dist\slurmify-backend.exe on
# Windows (the .exe extension is added automatically by the bootloader).
$BundlePath = "$RepoRoot\src-python\dist\slurmify-backend.exe"
if (-not (Test-Path $BundlePath)) {
    Write-Error "[build-sidecar] ERROR: PyInstaller did not produce $BundlePath"
}

# ── Move into Tauri's binaries\ folder under the host-triple name ─────
$BinDir       = "$RepoRoot\src-tauri\binaries"
$TargetPath   = "$BinDir\slurmify-backend-$HostTriple.exe"
if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir | Out-Null }
Move-Item -Force $BundlePath $TargetPath

if (-not (Test-Path $TargetPath)) {
    Write-Error "[build-sidecar] ERROR: expected sidecar at $TargetPath but it's missing."
}

# ── Sanity-launch the binary so Tauri's later spawn doesn't hit a
# silently-broken bundle.  We invoke with --help-style behavior by
# letting the sidecar print its `slurmify_ready` JSON on its own port,
# then SIGTERM it after a couple seconds.  Skip if PYINSTALLER_NO_SMOKE
# is set (CI sometimes can't bind ports).
if (-not $env:PYINSTALLER_NO_SMOKE) {
    Write-Host "[build-sidecar] Smoke-testing the bundle (start + kill)..."
    $proc = Start-Process -FilePath $TargetPath -PassThru -NoNewWindow -RedirectStandardOutput "$env:TEMP\slurm-sidecar-smoke.log"
    Start-Sleep -Seconds 4
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
        Write-Host "[build-sidecar] Smoke OK — bundle launched and was killed cleanly."
    } else {
        Write-Warning "[build-sidecar] Bundle exited prematurely. See $env:TEMP\slurm-sidecar-smoke.log"
        Get-Content "$env:TEMP\slurm-sidecar-smoke.log" -Tail 30 | Write-Host
    }
}

Write-Host ""
Write-Host "[build-sidecar] Done."
Write-Host "[build-sidecar] Output: $TargetPath"
