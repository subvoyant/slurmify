#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/build-dmg.sh — Produce a signed, notarized Slurmify .dmg
# ──────────────────────────────────────────────────────────────────────
#
# Orchestrates the full release build:
#
#   1. Clean prior artifacts so stale files can't sneak in.
#   2. Build the PyInstaller sidecar bundle (build-sidecar.sh).
#   3. Build the React frontend + Tauri Rust shell (`pnpm tauri build`)
#      with `APPLE_SIGNING_IDENTITY` set so Tauri's bundler signs the
#      .app with our Developer ID.
#   4. Defensive re-sign of the externalBin sidecar inside the .app
#      (issue tauri-apps/tauri#11992: Tauri's --deep pass doesn't
#      always apply hardened runtime + entitlements to externalBin
#      sidecars; we redo it explicitly to guarantee notarization
#      passes).  Then re-seal the .app's outer signature.
#   5. Notarize the .app via Apple's notary service and staple the
#      ticket.
#   6. Repackage the DMG with hdiutil + LICENSE + tester README +
#      Applications symlink (replaces Tauri's auto-generated DMG).
#   7. Sign the DMG itself.
#   8. Print the path to the produced .dmg + a smoke-test reminder.
#
# Output:
#   src-tauri/target/release/bundle/dmg/SIENA Slurmer <version>.dmg
#
# Tested only on macOS arm64 (Apple Silicon).  An Intel-Mac arm64 build
# would also work; universal2 (arm64+x86_64) is NOT supported by this
# script — would need a separate PyInstaller pass per arch and a
# `lipo`-merged binary.  Punt that until needed.
#
# ── Apple credentials ──────────────────────────────────────────────────
# • TEAM_ID + APPLE_ID below are public-ish (they were already in the
#   v0.1.x build.sh) so they live in source.
# • The app-specific password is NOT in source.  Instead, the script
#   expects a notarytool keychain profile named `slurmify-notary` (or
#   override via $NOTARY_PROFILE env var).  One-time setup:
#
#     xcrun notarytool store-credentials slurmify-notary \
#       --apple-id  subvoyant@me.com \
#       --team-id   W6442578P4 \
#       --password  <app-specific-password-from-appleid.apple.com>
#
#   App-specific passwords come from
#   https://appleid.apple.com → Sign-In and Security → App-Specific
#   Passwords (the same one v0.1.x's build.sh used; ask the team if
#   you need it).
#
#   The script bails out with that exact instruction if the profile
#   doesn't exist, so a fresh build host is one keychain-store away
#   from a working build.
#
# Prereqs (one-time):
#   • Apple Developer ID Application certificate installed in the
#     Keychain (Xcode → Settings → Accounts → Manage Certificates).
#   • notarytool keychain profile (see above).
#   • Rust toolchain (rustup) with the `aarch64-apple-darwin` target.
#   • Node + pnpm (`corepack enable` then `pnpm i`).
#   • Python 3.11+ in a venv with backend deps installed:
#       cd src-python
#       python3 -m venv .venv && source .venv/bin/activate
#       pip install -e ".[dev]"
#     The build-sidecar.sh script picks up `python3` by default; set
#     $PY to override.
#
# Usage:
#   ./scripts/build-dmg.sh                # full build
#   SKIP_SIDECAR=1 ./scripts/build-dmg.sh # reuse existing sidecar build
#   SKIP_NOTARIZE=1 ./scripts/build-dmg.sh # signing only (faster local
#                                          # smoke-tests; do NOT ship)
#   NOTARY_PROFILE=other-profile ./scripts/build-dmg.sh
#   PY=/path/to/.venv/bin/python ./scripts/build-dmg.sh
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Apple developer identity ───────────────────────────────────────────
# Inherited from v0.1.x's build.sh.  These are the team's existing
# credentials; if they ever change, update both places (this script and
# the legacy build.sh, until that file is removed).
TEAM_ID="W6442578P4"
APPLE_ID="subvoyant@me.com"
NOTARY_PROFILE="${NOTARY_PROFILE:-slurmify-notary}"
ENTITLEMENTS="$REPO_ROOT/src-tauri/entitlements.plist"

# ── Step 0: sanity ─────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════"
echo "[build-dmg] Building Slurmify .dmg from $REPO_ROOT"
echo "════════════════════════════════════════════════════════════════"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "[build-dmg] ERROR: this script targets macOS only.  Detected $(uname)."
    exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
    echo "[build-dmg] ERROR: pnpm not found.  Install via `corepack enable`."
    exit 1
fi

if ! command -v rustc >/dev/null 2>&1; then
    echo "[build-dmg] ERROR: rustc not found.  Install via https://rustup.rs"
    exit 1
fi

# ── Step 0b: Apple-side pre-flight ────────────────────────────────────
# Resolve the Developer ID Application cert dynamically from the
# keychain — same trick as the legacy build.sh — so we don't hard-code
# the SHA or the full identity string in source.  `security
# find-identity` is reliable; the find-certificate pipeline isn't.
SIGN_ID="$(security find-identity -v -p codesigning \
    | grep "Developer ID Application" \
    | head -1 \
    | sed 's/.*"\(.*\)".*/\1/' || true)"

if [[ -z "$SIGN_ID" ]]; then
    cat >&2 <<EOF
[build-dmg] ERROR: No 'Developer ID Application' certificate found in the keychain.
            Open Xcode → Settings → Accounts, sign in with the
            Subvoyant Apple ID ($APPLE_ID), and click 'Manage Certificates…'
            to download the cert, then re-run this script.
EOF
    exit 1
fi
echo "[build-dmg] Code signing identity: $SIGN_ID"

if [[ ! -f "$ENTITLEMENTS" ]]; then
    echo "[build-dmg] ERROR: entitlements file missing: $ENTITLEMENTS" >&2
    exit 1
fi

# Verify the notarytool keychain profile exists.  We check by asking
# notarytool to print history; an invalid profile errors out.  Suppress
# stdout so the success path is quiet; on failure print actionable
# setup instructions.
if [[ "${SKIP_NOTARIZE:-0}" != "1" ]]; then
    if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
        cat >&2 <<EOF
[build-dmg] ERROR: notarytool keychain profile '$NOTARY_PROFILE' not found.
            One-time setup (paste this into your terminal):

              xcrun notarytool store-credentials $NOTARY_PROFILE \\
                  --apple-id "$APPLE_ID" \\
                  --team-id  "$TEAM_ID" \\
                  --password "<app-specific-password-from-appleid.apple.com>"

            App-specific passwords live at
            https://appleid.apple.com → Sign-In and Security →
            App-Specific Passwords (the team has an existing one;
            ask Subvoyant ops if you need it).

            Once stored, re-run ./scripts/build-dmg.sh.

            (To skip notarization for a local smoke-test build,
            re-run with SKIP_NOTARIZE=1 — but DO NOT ship that DMG.)
EOF
        exit 1
    fi
fi

# ── Step 1: clean prior bundle artifacts ──────────────────────────────
# Removing the prior .dmg/.app prevents stale files (especially a
# pre-Phase-D bundle that's missing the sidecar) from being mistaken
# for the new build.  We DON'T clean target/release otherwise — that
# would force a full Rust recompile which takes minutes.
#
# Also nuke dist/ — Vite's prepareOutDir step does this internally,
# but if a previous build crashed mid-write OR another tool dropped
# files into dist/ (e.g., an old Tauri version putting .app
# intermediates there), Vite chokes with "ENOTEMPTY".  Easier to
# clean it ourselves than to keep diagnosing what wrote into it.
echo ""
echo "[build-dmg] Cleaning prior bundle output…"
rm -rf "$REPO_ROOT/src-tauri/target/release/bundle"
rm -rf "$REPO_ROOT/dist"

# ── Step 2: build the Python sidecar ──────────────────────────────────
if [[ "${SKIP_SIDECAR:-0}" == "1" ]]; then
    echo ""
    echo "[build-dmg] SKIP_SIDECAR=1 — reusing existing src-tauri/binaries/"
    if ! ls "$REPO_ROOT/src-tauri/binaries/slurmify-backend-"*"-apple-darwin" >/dev/null 2>&1; then
        echo "[build-dmg] ERROR: SKIP_SIDECAR set but no sidecar bundle exists."
        echo "                   Run without SKIP_SIDECAR first."
        exit 1
    fi
else
    echo ""
    echo "[build-dmg] Building Python sidecar…"
    bash "$SCRIPT_DIR/build-sidecar.sh"
fi

# ── Step 3: tauri build (frontend + rust + .app + Tauri's own .dmg) ───
# Tauri's bundler runs vite build first (per the beforeBuildCommand in
# tauri.conf.json), then compiles the Rust shell, then packs the .app
# and produces a .dmg.  Sidecar is auto-included via the externalBin
# entry we added in tauri.conf.json.
#
# APPLE_SIGNING_IDENTITY is read by Tauri's bundler and triggers
# inside-out codesigning of the .app with `--options runtime` and our
# entitlements file (configured via tauri.conf.json's
# bundle.macOS.entitlements).  We deliberately do NOT set APPLE_ID /
# APPLE_PASSWORD here — Tauri would otherwise try to notarize during
# `tauri build`, which we want to control ourselves so we can use the
# notarytool keychain profile (no plaintext credentials).
#
# Notes:
#   • If APPLE_SIGNING_IDENTITY is set but the cert isn't in the
#     keychain, Tauri's build fails with "no identity found", which
#     the Step-0b find-identity check would already have caught.
#   • Tauri's own .dmg output is discarded by Step 4 (we re-pack with
#     hdiutil).  We let Tauri build it anyway because the cost is
#     negligible and skipping requires conditional config.
echo ""
echo "[build-dmg] Running pnpm tauri build (APPLE_SIGNING_IDENTITY set)…"
APPLE_SIGNING_IDENTITY="$SIGN_ID" pnpm tauri build

# ── Step 4: re-package the DMG with version-stamped names + extras ───
# Tauri's default DMG output is "SIENA Slurmer_<version>_<arch>.dmg" with
# only the .app inside.  We want:
#   • A cleanly-named DMG:   "SIENA Slurmer <version>.dmg"
#   • A version-stamped .app: "SIENA Slurmer <version>.app"
#     (so Max can keep multiple builds in /Applications and tell which
#     is which at a glance.  Bundle ID is unchanged, so macOS still
#     treats successive builds as the same app.)
#   • LICENSE bundled at the DMG root (legal — GPL-3 distribution
#     requires the license travel with the binary).
#   • The tester README at the DMG root so Max sees install + bypass
#     instructions without having to poke inside the .app bundle.
#   • An /Applications symlink so the DMG opens with the canonical
#     "drag to Applications" layout.
#
# We extract the version from tauri.conf.json so this script never
# drifts from the canonical version source.  Using python3 because
# jq isn't guaranteed to be installed on every dev's Mac and the
# Tauri toolchain already pulls in a Python (the sidecar build).
VERSION="$(python3 -c "import json,sys; print(json.load(open('src-tauri/tauri.conf.json'))['version'])")"
if [[ -z "$VERSION" ]]; then
    echo "[build-dmg] ERROR: could not read version from src-tauri/tauri.conf.json"
    exit 1
fi
echo ""
echo "[build-dmg] Re-packaging DMG with version $VERSION + extras…"

BUNDLE_OUT="$REPO_ROOT/src-tauri/target/release/bundle"
TAURI_APP_PATH="$(find "$BUNDLE_OUT/macos" -name '*.app' -type d | head -n1)"
if [[ -z "$TAURI_APP_PATH" ]]; then
    echo "[build-dmg] ERROR: no .app produced by tauri build under $BUNDLE_OUT/macos"
    exit 1
fi

# Discard the auto-generated DMG.  We're about to build a custom one
# in its place; leaving the old one around would confuse the "find
# *.dmg" step below and risk shipping the wrong artifact.
rm -f "$BUNDLE_OUT/dmg/"*.dmg

# ── Step 3b: defensive sidecar re-sign + .app re-seal ────────────────
# Tauri's --deep codesign during `tauri build` signs every Mach-O it
# walks, but its handling of externalBin children is not always the
# same as the outer bundle: the sidecar (slurmify-backend) is a
# PyInstaller onefile, which:
#
#   1. self-extracts at runtime to /tmp and execs the embedded
#      Python interpreter — without `com.apple.security.cs.disable-
#      library-validation` the load fails on any non-Apple-signed
#      .so/.dylib (numpy, scipy, soundfile, …);
#   2. needs `com.apple.security.cs.allow-unsigned-executable-memory`
#      because the embedded interpreter writes machine code into
#      executable pages on first run.
#
# Both are in our entitlements file already (used for the .app), but
# Tauri's sidecar signing has historically dropped them on
# externalBin children — see github.com/tauri-apps/tauri#11992.  Rather
# than rely on Tauri getting it right on this version, we redo the
# sidecar's signature explicitly with the right options + entitlements,
# then re-seal the outer .app so its CodeResources reflects the new
# inner signature.  No-op if Tauri did the right thing already.
echo ""
echo "[build-dmg] Re-signing sidecar (hardened runtime + entitlements)…"
SIDECAR_IN_APP="$TAURI_APP_PATH/Contents/MacOS/slurmify-backend"
if [[ ! -f "$SIDECAR_IN_APP" ]]; then
    echo "[build-dmg] ERROR: sidecar binary missing at $SIDECAR_IN_APP" >&2
    echo "                   Did externalBin in tauri.conf.json change?" >&2
    exit 1
fi
codesign --force --options runtime --timestamp \
    --sign "$SIGN_ID" \
    --entitlements "$ENTITLEMENTS" \
    "$SIDECAR_IN_APP"
echo "[build-dmg] Re-sealing .app outer signature…"
codesign --force --options runtime --timestamp \
    --sign "$SIGN_ID" \
    --entitlements "$ENTITLEMENTS" \
    "$TAURI_APP_PATH"
codesign --verify --deep --strict --verbose=2 "$TAURI_APP_PATH"
echo "[build-dmg] Signature verified."

# ── Step 3c: notarize the .app and staple ─────────────────────────────
# notarytool wants a zip (or a flat single file).  We zip the .app
# with `ditto -c -k --keepParent`, submit, wait for accept, and staple
# the ticket onto the .app on disk so Gatekeeper doesn't need to
# re-check with Apple at every launch.
#
# After stapling, the .app contains a notarization ticket that the
# DMG repacking step (below) will carry along — no need to staple
# again on the copy inside the DMG.  We ALSO staple the DMG at the
# end as belt-and-braces (some macOS versions verify the DMG-level
# ticket on first mount).
if [[ "${SKIP_NOTARIZE:-0}" == "1" ]]; then
    echo ""
    echo "[build-dmg] SKIP_NOTARIZE=1 — leaving .app un-notarized."
    echo "            The resulting DMG is for local smoke-testing only;"
    echo "            do NOT ship it to testers (Sequoia will refuse)."
else
    echo ""
    echo "[build-dmg] Notarizing .app (this typically takes 1–5 minutes)…"
    NOTARIZE_ZIP="$BUNDLE_OUT/macos/slurmify-notarize.zip"
    rm -f "$NOTARIZE_ZIP"
    ditto -c -k --keepParent "$TAURI_APP_PATH" "$NOTARIZE_ZIP"
    xcrun notarytool submit "$NOTARIZE_ZIP" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait
    rm -f "$NOTARIZE_ZIP"

    echo "[build-dmg] Stapling notarization ticket onto .app…"
    xcrun stapler staple "$TAURI_APP_PATH"
    xcrun stapler validate "$TAURI_APP_PATH"
    echo "[build-dmg] Notarization stapled and verified."
fi

# Versioned names — used for both the staged .app and the final DMG.
APP_VERSIONED_NAME="SIENA Slurmer ${VERSION}.app"
DMG_FINAL_NAME="SIENA Slurmer ${VERSION}.dmg"
DMG_FINAL_PATH="$BUNDLE_OUT/dmg/${DMG_FINAL_NAME}"

# Stage everything in a temp dir.  cp -R the .app under its versioned
# name (this preserves the bundle structure but renames the top-level
# folder; codesign signs contents-by-hash so renaming the .app does
# NOT invalidate any signature).
DMG_STAGE="$(mktemp -d -t slurm-dmg-stage)"
trap 'rm -rf "$DMG_STAGE"' EXIT

cp -R "$TAURI_APP_PATH" "$DMG_STAGE/$APP_VERSIONED_NAME"

# Bundle LICENSE — GPL-3 redistribution requirement, and Max should
# see the third-party notices (rubberband, ffmpeg/x264, librosa…)
# without having to dig into the .app's Resources/.
if [[ -f "$REPO_ROOT/LICENSE" ]]; then
    cp "$REPO_ROOT/LICENSE" "$DMG_STAGE/LICENSE"
else
    echo "[build-dmg] WARN: LICENSE not found at repo root — DMG will ship without it."
fi

# Bundle the tester README under a friendlier name so it sorts at the
# top of the DMG window and reads like a doc rather than a dotfile.
if [[ -f "$REPO_ROOT/docs/TESTER_README.md" ]]; then
    cp "$REPO_ROOT/docs/TESTER_README.md" "$DMG_STAGE/Read Me — Tester Notes.md"
else
    echo "[build-dmg] WARN: docs/TESTER_README.md not found — DMG will ship without it."
fi

# /Applications symlink — gives the DMG the canonical drag-to-install
# layout testers already know.
ln -s /Applications "$DMG_STAGE/Applications"

# Build the DMG with hdiutil (always available on macOS).  UDZO =
# zlib-compressed read-only — the standard for distribution DMGs.
mkdir -p "$BUNDLE_OUT/dmg"
hdiutil create \
    -volname "SIENA Slurmer ${VERSION}" \
    -srcfolder "$DMG_STAGE" \
    -ov \
    -format UDZO \
    "$DMG_FINAL_PATH" >/dev/null

rm -rf "$DMG_STAGE"
trap - EXIT

# ── Step 4b: sign the DMG itself ──────────────────────────────────────
# The .app inside is already signed + (when SKIP_NOTARIZE!=1) stapled,
# so Gatekeeper would accept the .app even if the DMG were unsigned —
# but signing the DMG keeps `xcrun stapler` happy and avoids the
# "this disk image isn't signed" warning some macOS versions show on
# mount.
echo ""
echo "[build-dmg] Signing DMG…"
codesign --force --sign "$SIGN_ID" --timestamp "$DMG_FINAL_PATH"

# ── Step 4c: notarize + staple the DMG ────────────────────────────────
# Stapling the DMG is belt-and-braces: the .app inside is already
# stapled (Step 3c), but stapling the DMG too means first-mount on a
# tester's Mac doesn't have to phone home to Apple to verify the
# .app's notarization — the DMG already carries the ticket.  Some
# macOS versions (Sequoia in particular) treat a stapled DMG as a
# stronger trust signal than a stapled .app alone.
if [[ "${SKIP_NOTARIZE:-0}" == "1" ]]; then
    echo "[build-dmg] SKIP_NOTARIZE=1 — DMG is signed but NOT notarized."
else
    echo "[build-dmg] Notarizing DMG (typically <1 min — content already accepted)…"
    xcrun notarytool submit "$DMG_FINAL_PATH" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait
    echo "[build-dmg] Stapling notarization ticket onto DMG…"
    xcrun stapler staple "$DMG_FINAL_PATH"
    xcrun stapler validate "$DMG_FINAL_PATH"
    echo "[build-dmg] DMG notarization stapled and verified."
fi

# ── Step 5: report ────────────────────────────────────────────────────
DMG_PATH="$DMG_FINAL_PATH"
# The .app at TAURI_APP_PATH still has its original name
# ("SIENA Slurmer.app") on disk — the renamed copy lives only inside
# the DMG.  Report both so the smoke-test path is unambiguous.
APP_PATH="$TAURI_APP_PATH"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "[build-dmg] DONE"
echo "════════════════════════════════════════════════════════════════"
if [[ -f "$DMG_PATH" ]]; then
    DMG_SIZE="$(du -h "$DMG_PATH" | cut -f1)"
    echo "  DMG:  $DMG_PATH  ($DMG_SIZE)"
    echo "        (contains: $APP_VERSIONED_NAME, LICENSE, Read Me — Tester Notes.md, Applications symlink)"
fi
if [[ -d "$APP_PATH" ]]; then
    APP_SIZE="$(du -sh "$APP_PATH" | cut -f1)"
    echo "  .app: $APP_PATH  ($APP_SIZE)"
    echo "        (smoke-test build — version-stamped name only applies inside the DMG)"
fi
echo ""
echo "  Smoke-test:"
echo "    open \"$APP_PATH\""
echo ""
if [[ "${SKIP_NOTARIZE:-0}" == "1" ]]; then
    echo "  ⚠  This build was produced with SKIP_NOTARIZE=1 — for local"
    echo "     smoke-testing only.  Sequoia/Sonoma testers will see the"
    echo "     'is damaged and can't be opened' Gatekeeper dialog.  Do"
    echo "     NOT distribute this DMG.  Re-run without SKIP_NOTARIZE."
else
    echo "  Build is signed and notarized — testers can double-click"
    echo "  the .app from the DMG without any Gatekeeper bypass dance."
fi
echo ""
echo "  Hand the DMG to Max:"
echo "    cp \"$DMG_PATH\" ~/Desktop/"
echo "════════════════════════════════════════════════════════════════"
