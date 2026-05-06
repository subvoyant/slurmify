#!/usr/bin/env bash
# =============================================================================
# build.sh — Build, sign, notarize, and package Subvoyant SIENA Slurmer.app
#
# Prerequisites (one-time):
#   brew install python ffmpeg rubberband create-dmg
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt
#
# Usage:
#   source .venv/bin/activate
#   ./build.sh
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURE THESE — fill in before first run
# =============================================================================
TEAM_ID="W6442578P4"
APPLE_ID="subvoyant@me.com"          # Apple ID for notarization
APP_PASSWORD="pgkq-ikzt-tpws-aqia"  # app-specific password from appleid.apple.com → Security
                                     # (format: xxxx-xxxx-xxxx-xxxx)
# =============================================================================

APP_NAME="Subvoyant SIENA Slurmer"   # display name — matches BUNDLE name in spec
APP_SAFE="SubvoyantSIENASlurmer"     # no spaces — used for DMG filename
BUNDLE_ID="com.subvoyant.siena.slurmer"
VERSION="0.1.3"
DIST_DIR="dist"
APP_PATH="${DIST_DIR}/${APP_NAME}.app"
DMG_NAME="${APP_SAFE}-${VERSION}.dmg"
ENTITLEMENTS="entitlements.plist"
ZIP_PATH="${DIST_DIR}/${APP_SAFE}.zip"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}▶ $*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
die()   { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# =============================================================================
# 0. Pre-flight checks
# =============================================================================
step "Pre-flight checks"

[[ -z "$APPLE_ID" ]]     && die "Set APPLE_ID at the top of build.sh"
[[ -z "$APP_PASSWORD" ]] && die "Set APP_PASSWORD at the top of build.sh (app-specific password from appleid.apple.com)"

command -v pyinstaller &>/dev/null || die "pyinstaller not found — activate the venv first: source .venv/bin/activate"
command -v rubberband  &>/dev/null || die "rubberband not found — run: brew install rubberband"
# hdiutil is always available on macOS; create-dmg adds a pretty Finder layout
# but requires Finder to be responsive (unreliable in automation). Use hdiutil.
CREATE_DMG=0

python -c "import imageio_ffmpeg" 2>/dev/null || die "imageio-ffmpeg not installed — run: pip install -r requirements.txt"

ok "All checks passed"

# =============================================================================
# 1. Clean previous build
# =============================================================================
step "Cleaning previous build"
rm -rf build dist rw.*.dmg   # full wipe — ensures app.py changes are always re-bundled
ok "Clean"

# =============================================================================
# 2. PyInstaller build
# =============================================================================
step "Running PyInstaller"
pyinstaller slurmify.spec --noconfirm
[[ -d "$APP_PATH" ]] || die "PyInstaller did not produce ${APP_PATH}"
ok "Bundle created: ${APP_PATH}"

# =============================================================================
# 3. Fix rubberband dylib paths (make binary self-contained)
#    install_name_tool rewrites @rpath references to @executable_path
#    so the vendored binary doesn't try to load Homebrew dylibs at runtime.
# =============================================================================
step "Fixing rubberband dylib paths"
# PyInstaller 6 places all bundled binaries/data in Contents/Frameworks/ (not MacOS/)
# so sys._MEIPASS inside the app resolves to Contents/Frameworks/.
RB_BIN="${APP_PATH}/Contents/Frameworks/bin/rubberband"
FRAMEWORKS_DIR="${APP_PATH}/Contents/Frameworks"
mkdir -p "$FRAMEWORKS_DIR"

if [[ ! -f "$RB_BIN" ]]; then
    die "rubberband binary not found at ${RB_BIN} — check slurmify.spec binaries list"
fi

# Find all non-system dylibs rubberband links against and copy them in.
while IFS= read -r line; do
    dylib=$(echo "$line" | awk '{print $1}')
    # Skip system libs and already-fixed references
    [[ "$dylib" == /usr/lib/* ]]        && continue
    [[ "$dylib" == /System/* ]]         && continue
    [[ "$dylib" == @* ]]                && continue
    [[ ! -f "$dylib" ]]                 && { warn "  dylib not found, skipping: $dylib"; continue; }

    libname=$(basename "$dylib")
    dest="${FRAMEWORKS_DIR}/${libname}"
    cp -n "$dylib" "$dest" 2>/dev/null || true
    chmod 755 "$dest"

    # @loader_path inside Contents/Frameworks/bin/ points one level up to Contents/Frameworks/
    # which is where we copied the dylib — this keeps the reference self-contained.
    install_name_tool -change "$dylib" "@loader_path/../${libname}" "$RB_BIN" 2>/dev/null || true
    ok "  bundled: ${libname}"
done < <(otool -L "$RB_BIN" | tail -n +2)

ok "rubberband dylibs patched"

# =============================================================================
# 4. Deep code-sign with hardened runtime
#    Sign inner binaries first (inside-out), then the .app itself.
# =============================================================================
step "Code-signing (Team ID: ${TEAM_ID})"

# Resolve the full signing identity string from the keychain once, up front.
# `security find-identity` is reliable; the find-certificate pipeline is not.
SIGN_ID=$(security find-identity -v -p codesigning \
    | grep "Developer ID Application" \
    | head -1 \
    | sed 's/.*"\(.*\)".*/\1/')

if [[ -z "$SIGN_ID" ]]; then
    die "No 'Developer ID Application' certificate found in keychain.\nOpen Xcode → Settings → Accounts and make sure your certificate is downloaded."
fi
ok "Signing identity: ${SIGN_ID}"

# Sign all .dylib and .so files inside the bundle (parentheses required with -o)
find "${APP_PATH}" \( -name "*.dylib" -o -name "*.so" \) 2>/dev/null \
  | while read -r f; do
        codesign --force --options runtime --timestamp \
            --sign "$SIGN_ID" --entitlements "$ENTITLEMENTS" \
            "$f" 2>/dev/null || true
    done

# Sign vendored CLI binaries
find "${APP_PATH}/Contents/Frameworks/bin" -type f 2>/dev/null \
  | while read -r f; do
        codesign --force --options runtime --timestamp \
            --sign "$SIGN_ID" --entitlements "$ENTITLEMENTS" \
            "$f" 2>/dev/null || true
    done

# Sign the .app bundle itself (--deep catches anything remaining)
codesign \
    --deep --force --options runtime --timestamp \
    --sign "$SIGN_ID" \
    --entitlements "$ENTITLEMENTS" \
    "$APP_PATH"

ok "Code-signing complete"

# Verify
codesign --verify --deep --strict "$APP_PATH" && ok "Signature verified" || die "Signature verification failed"

# =============================================================================
# 5. Notarize
# =============================================================================
step "Notarizing (this takes 1–5 minutes)"

# Zip for submission
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

xcrun notarytool submit "$ZIP_PATH" \
    --apple-id    "$APPLE_ID" \
    --team-id     "$TEAM_ID" \
    --password    "$APP_PASSWORD" \
    --wait \
    --progress

ok "Notarization accepted"

# =============================================================================
# 6. Staple notarization ticket
# =============================================================================
step "Stapling notarization ticket"
xcrun stapler staple "$APP_PATH"
xcrun stapler validate "$APP_PATH" && ok "Staple verified" || die "Staple validation failed"

# =============================================================================
# 7. Create DMG
# =============================================================================
step "Creating DMG"
rm -f "${DMG_NAME}"

if [[ "$CREATE_DMG" -eq 1 ]]; then
    create-dmg \
        --volname "${APP_NAME}" \
        --volicon "icon/icons/subvoyant.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 128 \
        --icon "${APP_NAME}.app" 175 190 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 425 190 \
        "${DMG_NAME}" \
        "${DIST_DIR}/"
else
    # Stage the .app alongside the LICENSE, beta-test notes, and a symlink to
    # /Applications so the DMG opens with the canonical "drag to Applications"
    # layout — and so testers can read the license + tester notes without
    # poking inside the .app bundle.
    DMG_STAGE="$(mktemp -d -t slurm-dmg-stage)"
    trap 'rm -rf "$DMG_STAGE"' EXIT
    cp -R "$APP_PATH" "$DMG_STAGE/"
    [[ -f LICENSE ]] && cp LICENSE "$DMG_STAGE/LICENSE"
    [[ -f SLURMER_BETATEST_INSTRUCTIONS.md ]] \
        && cp SLURMER_BETATEST_INSTRUCTIONS.md "$DMG_STAGE/Read Me — Beta Test Notes.md"
    [[ -f SLURMCORE_COMPARISON.md ]] \
        && cp SLURMCORE_COMPARISON.md "$DMG_STAGE/Slurmify vs Slurmcore — Method Guide.md"
    ln -s /Applications "$DMG_STAGE/Applications"

    hdiutil create \
        -volname "${APP_NAME}" \
        -srcfolder "$DMG_STAGE" \
        -ov \
        -format UDZO \
        "${DMG_NAME}"

    rm -rf "$DMG_STAGE"
    trap - EXIT
fi

ok "DMG created: ${DMG_NAME}"

# =============================================================================
# 8. Sign the DMG itself
# =============================================================================
step "Signing DMG"
codesign --sign "$SIGN_ID" --timestamp "${DMG_NAME}"
ok "DMG signed"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓  ${DMG_NAME} is ready to send to Max.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Max just needs to:"
echo "  1. Open the DMG"
echo "  2. Drag 'Subvoyant SIENA Slurmer' to Applications"
echo "  3. Double-click it — browser opens, he's in"
echo ""
