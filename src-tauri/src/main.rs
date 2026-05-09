// ──────────────────────────────────────────────────────────────────────
// src-tauri/src/main.rs — Slurmify Tauri shell entry
// ──────────────────────────────────────────────────────────────────────
// Tauri 2 puts almost everything in lib.rs so the same code can target
// both desktop and (eventually) mobile.  This file is a thin entry
// that calls run().  Don't add logic here — add it to lib.rs.
//
// The cfg_attr line suppresses the Windows console window when the app
// is launched as a release binary.  Harmless on macOS; required on
// Windows so users don't see a flashing console behind the Tauri window.
// ──────────────────────────────────────────────────────────────────────

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    slurmify_lib::run()
}
