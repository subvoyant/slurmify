; ─────────────────────────────────────────────────────────────────────
; src-tauri/nsis-hooks.nsh — NSIS hooks for the SIENA Slurmer installer
; ─────────────────────────────────────────────────────────────────────
;
; Tauri 2's NSIS bundler stitches this file's macros into its generated
; installer.nsi at the points it documents:
;
;   NSIS_HOOK_PREINSTALL   — runs immediately before files are
;                            extracted into $INSTDIR.  Anything that
;                            needs to release file locks (running .exes)
;                            belongs here.
;   NSIS_HOOK_POSTINSTALL  — runs after files are written but before
;                            the success page.  Useful for "first-run"
;                            setup steps; we don't need any today.
;   NSIS_HOOK_PREUNINSTALL — runs before file deletion during uninstall.
;                            Mirror of PREINSTALL — same need to kill
;                            the running app so we can delete its .exes.
;   NSIS_HOOK_POSTUNINSTALL — runs after file deletion.
;
; Reference for the macro hook names + invocation order:
;   https://v2.tauri.app/distribute/windows-installer/#installer-hooks
;
; Why we need PREINSTALL: the v0.2.1-win-4 build hit the classic NSIS
; "Error opening file for writing: …\slurmify-backend.exe" dialog when
; the user re-ran the installer over a running install of -win-3.  The
; previous app + its Python sidecar held file locks on the .exe paths
; the installer was about to overwrite; NSIS surfaced the lock as the
; Abort/Retry/Ignore prompt.  The user had to open Task Manager, end
; three processes (SIENA Slurmer.exe, siena-slurmer.exe,
; slurmify-backend.exe), and click Retry.  This hook does that work
; automatically before extraction starts.
;
; nsExec::Exec runs the command with stdout/stderr discarded and the
; exit code pushed onto the stack.  We Pop the exit code into $0 to
; clear the stack (NSIS leaks if you don't), but we DON'T act on it —
; taskkill exits 128 when the process isn't running, which is
; expected on a fresh install where there's nothing to kill.
;
; /F = force termination (no graceful shutdown ask).
; /T = also terminate child processes.  Critical for slurmify-backend
;      because the Tauri shell spawns it as a child; killing the shell
;      should kill the sidecar via job-object cleanup, but /T makes
;      sure.
; /IM = match by image (executable) name.  We list every possible name
;      the app might appear as because Tauri's productName is
;      "SIENA Slurmer" but the bundled .exe on disk is sometimes
;      "siena-slurmer.exe" depending on bundler version.
;
; The Sleep 500 after the kills gives Windows a moment to release the
; file handles before NSIS tries to overwrite them.  Without it the
; race window is small but non-zero.
; ─────────────────────────────────────────────────────────────────────

!macro NSIS_HOOK_PREINSTALL
    DetailPrint "Closing any running SIENA Slurmer processes before install..."
    nsExec::Exec 'taskkill /F /T /IM "SIENA Slurmer.exe"'
    Pop $0
    nsExec::Exec 'taskkill /F /T /IM "siena-slurmer.exe"'
    Pop $0
    nsExec::Exec 'taskkill /F /T /IM "slurmify-backend.exe"'
    Pop $0
    Sleep 500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
    DetailPrint "Closing any running SIENA Slurmer processes before uninstall..."
    nsExec::Exec 'taskkill /F /T /IM "SIENA Slurmer.exe"'
    Pop $0
    nsExec::Exec 'taskkill /F /T /IM "siena-slurmer.exe"'
    Pop $0
    nsExec::Exec 'taskkill /F /T /IM "slurmify-backend.exe"'
    Pop $0
    Sleep 500
!macroend
