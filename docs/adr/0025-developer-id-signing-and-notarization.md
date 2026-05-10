# ADR-0025: Developer ID signing + notarization in `build-dmg.sh`

- **Status:** Accepted
- **Date:** 2026-05-09 (v0.2.0.x)

## Context

The original v0.2.0 builds shipped unsigned. On Sequoia and recent
Sonoma, macOS shows a hostile "**[App] is damaged and can't be
opened**" dialog with no Open button when an unsigned, quarantined
downloaded app tries to launch — a regression from the older
"unidentified developer / right-click → Open" path.

Tester Max hit exactly this: downloaded the v0.2.0 DMG via Chrome
(which attaches `com.apple.quarantine`), couldn't open the .app at
all. Meanwhile the team's own Macs had no problem — they had built
the DMG locally, so no quarantine bit was set.

The team has an existing Apple Developer ID (Team `W6442578P4`,
Apple ID `subvoyant@me.com`) plus an app-specific password for
notarization, set up for the v0.1.x build. That setup was wired into
the legacy `build.sh` at the repo root but had never been ported into
the v0.2.0 `scripts/build-dmg.sh`.

The v0.2.0 build is structurally different from v0.1.x in ways that
make signing+notarization more delicate:

1. **Two binaries inside the .app**, not one. `Contents/MacOS/`
   contains both the Tauri Rust shell (`slurmify`) and the
   PyInstaller onefile sidecar (`slurmify-backend`).
2. **The sidecar is a self-extracting payload**. When invoked, it
   drops its embedded compressed data into a temp dir and execs the
   embedded Python interpreter. macOS's hardened runtime kills
   self-modifying processes by default; the sidecar needs explicit
   entitlements (`com.apple.security.cs.allow-unsigned-executable-memory`
   and `com.apple.security.cs.disable-library-validation`).
3. **Tauri's `--deep` codesign doesn't always carry entitlements
   onto externalBin children** ([tauri#11992]). Even when Tauri
   appears to sign the sidecar, the inner signature can lack the
   hardened-runtime flag or skip the entitlements file, which
   either fails notarization or causes the sidecar to crash on
   first run.

[tauri#11992]: https://github.com/tauri-apps/tauri/issues/11992

## Decision

`scripts/build-dmg.sh` now runs the full sign + notarize + staple
pipeline. The sequence:

### Pre-flight

- `security find-identity -v -p codesigning | grep "Developer ID
  Application" | head -1` resolves the signing identity dynamically
  from the keychain. Same trick the legacy `build.sh` used; avoids
  hard-coding the SHA or the full identity string in source. If no
  cert is installed, the script bails with an Xcode → Settings →
  Accounts setup hint.
- `xcrun notarytool history --keychain-profile slurmify-notary` is
  used as a probe to confirm the notarization keychain profile
  exists. If missing, the script prints the exact
  `xcrun notarytool store-credentials …` command needed to set it up
  (one-time, per build host) and exits. The app-specific password
  itself is **never** in source — it lives only in the user's
  keychain.

### Build + sign

1. Build the sidecar (`build-sidecar.sh`).
2. Run `APPLE_SIGNING_IDENTITY="$SIGN_ID" pnpm tauri build`. Tauri's
   bundler reads that env var and codesigns the .app inside-out
   with `--options runtime` and the entitlements file referenced
   by `tauri.conf.json` (`bundle.macOS.entitlements`).
3. **Re-sign the sidecar explicitly** with the same options +
   entitlements. This is the ADR-0025 mitigation for [tauri#11992]:
   we don't trust Tauri's externalBin signing to carry the hardened
   runtime + entitlements, so we redo it.
4. Re-seal the .app's outer signature so its `_CodeSignature/CodeResources`
   reflects the new inner signature. Without this re-seal,
   `codesign --verify --deep --strict` fails with
   "resource envelope is obsolete".

### Notarize + staple

5. Zip the .app with `ditto -c -k --keepParent` and submit to
   `xcrun notarytool submit … --keychain-profile slurmify-notary
   --wait`. Typical turnaround: 1–5 minutes.
6. `xcrun stapler staple` the ticket onto the .app on disk so future
   first-launches don't have to call home to Apple.
7. Repackage our custom DMG (existing logic — staged folder with
   LICENSE + tester README + Applications symlink). The stapled
   .app is copied as-is.
8. Sign the DMG, then submit it to notarytool too, then staple
   the DMG. Belt-and-braces: stapling the DMG means first-mount on
   a tester's Mac doesn't require Apple connectivity to verify the
   ticket — the DMG carries its own.

### Local smoke-test escape hatch

Notarization adds 1–5 minutes per build. For purely local UI
smoke-testing, `SKIP_NOTARIZE=1 ./scripts/build-dmg.sh` skips both
notarization rounds (the .app and DMG are still signed). The script
prints a loud warning that the resulting DMG is for local use only —
Sequoia testers will hit the "is damaged" dialog on a non-notarized
build.

## Consequences

### Positive

- **Testers double-click and the app opens.** No xattr commands, no
  right-click → Open dance, no Privacy & Security trip.
- **Hardened runtime is correct on the sidecar.** PyInstaller's
  self-extract works, scipy/numpy/soundfile load, librosa's
  audioread + ffmpeg subprocess fallback works.
- **No plaintext credentials in source.** The legacy `build.sh`
  committed the app-specific password directly in the script.
  Build-dmg.sh moves to keychain-profile auth — TEAM_ID and APPLE_ID
  are visible (they're not secret) but the password lives only in
  the build host's keychain.
- **Build host setup is reproducible.** A fresh Mac with the cert
  installed via Xcode and the keychain profile stored is one
  `./scripts/build-dmg.sh` invocation away from a shippable DMG.

### Negative

- **Build is now slower.** Notarization adds 1–5 minutes per build,
  doubled because we notarize both the .app and the DMG. Mitigated
  by `SKIP_NOTARIZE=1` for local iteration.
- **Network dependency at build time.** notarytool needs to reach
  Apple's notary service; an offline build host can't ship.
  `SKIP_NOTARIZE=1` works offline but produces undistributable DMGs.
- **One-time setup overhead per build host.** New machines need
  `xcrun notarytool store-credentials` once. Mitigated by the
  script's clear error message that includes the exact command.

### Neutral

- **The legacy `build.sh`** at the repo root still has the password
  in plaintext (v0.1.x posture). It's vestigial — v0.2.0 builds
  don't use it — but the password should be rotated and the file
  cleaned up when the v0.1.x branch is officially retired.
- **Tauri's own DMG output is still discarded.** We continue to
  use Tauri to produce the .app, then build our own DMG with hdiutil
  for layout reasons (LICENSE + tester notes + Applications symlink
  + version-stamped name). The signing pipeline operates on the
  Tauri-produced .app and on our hdiutil-produced DMG.

## Alternatives considered

1. **Use Tauri's built-in notarization (`APPLE_ID` + `APPLE_PASSWORD` +
   `APPLE_TEAM_ID` env vars).** Tauri 2 will notarize during
   `tauri build` if these are set. Rejected because:
     - It would either require the password in source (matching
       v0.1.x's mistake) or surfacing it via a different env-var
       fetch — net result: more complexity than just doing it
       ourselves with a keychain profile.
     - We discard Tauri's DMG and rebuild it, so we'd still need a
       second notarization round on our DMG anyway.
     - We need the explicit sidecar re-sign step (Step 3b) regardless,
       which has to happen between `tauri build` and notarization.
       Easier to control the whole sequence ourselves.

2. **Use App Store Connect API key (`APPLE_API_KEY` + `APPLE_API_ISSUER`)
   instead of an app-specific password.** Rejected as a future
   improvement: cleaner credential model (revocable, scoped), but
   requires generating + storing a `.p8` key file which is just a
   different secret-management problem. Not worth the migration cost
   right now.

3. **Codesign-only, no notarization.** Rejected: Sequoia needs a
   notarization ticket for downloaded apps to launch without
   Gatekeeper friction. Codesign-only works on the build host (no
   quarantine xattr) but breaks on every tester.

4. **Disable hardened runtime on the sidecar to avoid the [tauri#11992]
   workaround.** Rejected: Apple requires hardened runtime for
   notarization. Without it the notarytool submission gets rejected.

## Verification

After implementing this ADR, confirm:

```bash
# Inspect the signature on the produced .app:
codesign -dv --verbose=4 "src-tauri/target/release/bundle/macos/SIENA Slurmer.app"
# Should show:
#   Identifier=com.subvoyant.siena.slurmer
#   Authority=Developer ID Application: <name> (W6442578P4)
#   Authority=Developer ID Certification Authority
#   Authority=Apple Root CA
#   Hardened Runtime, run-time

# Confirm the sidecar inside has the same options + entitlements:
codesign -d --entitlements - "src-tauri/target/release/bundle/macos/SIENA Slurmer.app/Contents/MacOS/slurmify-backend"
# Should print our entitlements XML.

# Confirm staple is present and valid:
xcrun stapler validate "src-tauri/target/release/bundle/dmg/SIENA Slurmer 0.2.0.dmg"
# Should print:  The validate action worked!

# Spctl assessment (what Gatekeeper sees on a tester's Mac):
spctl -a -vv -t install "src-tauri/target/release/bundle/dmg/SIENA Slurmer 0.2.0.dmg"
# Should print:  accepted  source=Notarized Developer ID
```

A clean Mac that downloads the DMG via Chrome should open the .app
on first double-click with no dialogs.

## See also

- [ADR-0022](0022-tauri-react-migration.md) — the v0.2.0 architecture
  that introduced two binaries inside the .app (Tauri shell +
  PyInstaller sidecar) and the entitlements posture this ADR builds
  on.
- [ADR-0023](0023-bundle-cli-binaries-in-sidecar.md) — bundling
  ffmpeg + rubberband CLIs inside the sidecar; relevant because
  those bundled CLIs run inside the hardened-runtime sidecar process
  and rely on `disable-library-validation` working correctly.
- The legacy `build.sh` at the repo root — same credentials, same
  general pipeline; this ADR ports the approach to the v0.2.0
  Tauri-shell architecture.
- [tauri-apps/tauri#11992][tauri#11992] — the externalBin signing
  bug the Step 3b re-sign mitigates.
