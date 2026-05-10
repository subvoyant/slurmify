# ──────────────────────────────────────────────────────────────────────
# scripts/build-windows.ps1 — Produce a Windows NSIS installer
# ──────────────────────────────────────────────────────────────────────
#
# Windows equivalent of scripts/build-dmg.sh, with three differences:
#   1. No code signing (deferred — see docs/WINDOWS_BUILD.md).
#   2. NSIS installer instead of DMG (MSI is blocked on tauri#14681
#      whenever externalBin is configured, which it is for us).
#   3. PyInstaller produces a .exe, not a Mach-O binary.
#
# Pipeline:
#   1. Sanity-check toolchain (rustc, pnpm, python, ffmpeg, rubberband).
#   2. Clean prior bundle output to avoid stale-artifact confusion.
#   3. Build the PyInstaller sidecar via build-sidecar.ps1.
#   4. Run `pnpm tauri build --bundles nsis` to produce the installer.
#   5. Report the path to the produced -setup.exe.
#
# Output:
#   src-tauri\target\release\bundle\nsis\SIENA Slurmer_<version>_x64-setup.exe
#
# Prereqs (one-time on the build host — see docs/WINDOWS_BUILD.md §B.2):
#   - Rust toolchain + x86_64-pc-windows-msvc target
#   - Visual Studio Build Tools (MSVC linker)
#   - Node + pnpm
#   - Python 3.11+ in a venv with src-python deps installed
#   - ffmpeg.exe + rubberband.exe on PATH
#
# Usage (from the repo root, with the Python venv activated):
#     .\scripts\build-windows.ps1
#
# Skip the sidecar rebuild (faster iteration; only the Tauri side
# rebuilds):
#     $env:SKIP_SIDECAR = "1"
#     .\scripts\build-windows.ps1
# ──────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

if (-not $IsWindows -and ($PSVersionTable.PSEdition -ne "Desktop")) {
    Write-Error "[build-windows] This script is for Windows only. Use scripts/build-dmg.sh on macOS."
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

Write-Host ""
Write-Host "================================================================"
Write-Host "[build-windows] Building Slurmify Windows installer from $RepoRoot"
Write-Host "================================================================"

# ── Step 0: toolchain sanity ──────────────────────────────────────────
foreach ($cmd in @("rustc", "pnpm", "python")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Error "[build-windows] ERROR: '$cmd' not found on PATH. See docs/WINDOWS_BUILD.md §B.2."
    }
}
foreach ($cli in @("ffmpeg", "rubberband")) {
    $found = Get-Command $cli -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Error "[build-windows] ERROR: '$cli' not found on PATH. Run: choco install $cli"
    }
}

# ── Step 1: clean prior bundle artifacts ──────────────────────────────
# Tauri's bundler doesn't always clean up between runs (e.g., a prior
# MSI attempt leaves a half-baked .msi behind that confuses humans
# looking at the output dir).  Nuke the bundle/ tree.
$BundleOut = "$RepoRoot\src-tauri\target\release\bundle"
if (Test-Path $BundleOut) {
    Write-Host ""
    Write-Host "[build-windows] Cleaning prior bundle output..."
    Remove-Item -Recurse -Force $BundleOut
}

# Also nuke the Vite dist/ if Vite crashed mid-write on a prior run.
if (Test-Path "$RepoRoot\dist") {
    Write-Host "[build-windows] Cleaning dist/..."
    Remove-Item -Recurse -Force "$RepoRoot\dist"
}

# ── Step 2: build the Python sidecar ──────────────────────────────────
if ($env:SKIP_SIDECAR -eq "1") {
    Write-Host ""
    Write-Host "[build-windows] SKIP_SIDECAR=1 — reusing existing src-tauri\binaries\"
    $existing = Get-ChildItem "$RepoRoot\src-tauri\binaries\slurmify-backend-*-pc-windows-msvc.exe" -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Error @"
[build-windows] ERROR: SKIP_SIDECAR set but no Windows sidecar exists.
                Run without SKIP_SIDECAR first to produce the initial bundle.
"@
    }
} else {
    Write-Host ""
    Write-Host "[build-windows] Building Python sidecar..."
    & "$ScriptDir\build-sidecar.ps1"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[build-windows] Sidecar build failed."
    }
}

# ── Step 3: build the Tauri app + NSIS installer ──────────────────────
# `--bundles nsis` is REQUIRED on Windows.  Without it, Tauri tries to
# build MSI as well, which crashes at WiX/candle.exe time when
# externalBin is configured (tauri#14681).  Pinning to NSIS is the
# documented workaround until that bug is fixed upstream.
Write-Host ""
Write-Host "[build-windows] Running pnpm tauri build (--bundles nsis)..."
& pnpm tauri build --bundles nsis
if ($LASTEXITCODE -ne 0) {
    Write-Error "[build-windows] Tauri build failed."
}

# ── Step 4: report ────────────────────────────────────────────────────
$NsisOut = "$BundleOut\nsis"
if (-not (Test-Path $NsisOut)) {
    Write-Error "[build-windows] ERROR: no NSIS bundle produced under $NsisOut"
}

$Installer = Get-ChildItem "$NsisOut\*-setup.exe" | Select-Object -First 1
if (-not $Installer) {
    Write-Error "[build-windows] ERROR: no -setup.exe found under $NsisOut"
}

$SizeMb = [math]::Round($Installer.Length / 1MB, 1)

Write-Host ""
Write-Host "================================================================"
Write-Host "[build-windows] DONE"
Write-Host "================================================================"
Write-Host "  Installer: $($Installer.FullName)  ($SizeMb MB)"
Write-Host ""
Write-Host "  Smoke-test on this machine:"
Write-Host "    Start-Process '$($Installer.FullName)'"
Write-Host ""
Write-Host "  Bob will see Microsoft SmartScreen on first launch."
Write-Host "  Tell him: click 'More info' -> 'Run anyway' (one time)."
Write-Host "  See docs/TESTER_README_WINDOWS.md for the full handoff text."
Write-Host "================================================================"
