// ──────────────────────────────────────────────────────────────────────
// src-tauri/src/lib.rs — Slurmify Tauri shell
// ──────────────────────────────────────────────────────────────────────
//
// Phase A: opened a window with the React app.
// Phase B (this revision): expose `read_backend_discovery` so the
//   frontend can find the dev-mode Python backend without any
//   filesystem permissions on the JS side.
//
// Phase D will add:
//   • A `start_backend` command that spawns the Python sidecar via
//     tauri-plugin-shell, parses the stdout JSON ready line, and
//     emits a `backend-ready` event with the port (production mode).
//   • In dev mode the user runs `python src-python/server.py` in a
//     separate terminal; that process writes the discovery file we
//     read here.
// ──────────────────────────────────────────────────────────────────────

use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::process::Command;

// ── Backend discovery ─────────────────────────────────────────────────
// The Python sidecar (src-python/server.py) writes a small JSON file
// to the OS temp dir at startup containing the port it bound.  We
// read it from Rust because:
//
//   • Reading anywhere on disk from JS would require either a
//     permissive `fs:scope-temp-recursive` capability (broad — leaks
//     access to every temp file the system has) or a per-path scope
//     that's awkward to keep in sync with Python's tempfile.gettempdir().
//   • The Rust side has unrestricted filesystem access by default;
//     scoping it to ONE specific filename is the smallest possible
//     capability grant.
//   • std::env::temp_dir() and Python's tempfile.gettempdir() resolve
//     to the same path on macOS (both honor TMPDIR / fall back to
//     /tmp).  This matches because both are set by launchd at user
//     session start, so all of the user's processes see the same value.

/// Payload Python writes — must match write_discovery_file in server.py.
#[derive(Serialize, Deserialize, Debug)]
pub struct BackendDiscovery {
    pub port:       u16,
    pub pid:        u32,
    pub started_at: f64,
    pub version:    String,
}

/// Filename written by src-python/server.py's write_discovery_file().
/// Resolved against std::env::temp_dir() at call time.
const DISCOVERY_FILENAME: &str = "slurmify-backend.json";

/// Read the discovery file written by the Python backend.
///
/// Returns `Err("not found")` if the backend isn't running yet —
/// the frontend treats that as a normal "still waiting" state and
/// keeps polling.  Other errors (malformed JSON, permission denied)
/// surface verbatim so the user sees them in the connection-status
/// indicator.
#[tauri::command]
fn read_backend_discovery() -> Result<BackendDiscovery, String> {
    let path = env::temp_dir().join(DISCOVERY_FILENAME);
    if !path.exists() {
        return Err("not found".to_string());
    }
    let bytes = fs::read(&path)
        .map_err(|e| format!("could not read {}: {}", path.display(), e))?;
    serde_json::from_slice(&bytes)
        .map_err(|e| format!("malformed discovery file at {}: {}", path.display(), e))
}

// ── Reveal a folder in the OS file browser ────────────────────────────
//
// Bypasses Tauri's plugin-shell scope plumbing entirely.  We call
// std::process::Command directly, which has unrestricted access from
// Rust (the same way our FastAPI sidecar has unrestricted access).
//
// Per-platform handler list:
//   • macOS  → `open -R <path>` (reveals + selects in Finder).
//              Bare `open <path>` opens the dir as the active window.
//              We use `-R` which highlights the folder in its parent —
//              feels more like "reveal" than "navigate to".
//   • Linux  → `xdg-open <path>` (delegates to the desktop file
//              manager — Files / Dolphin / Nautilus).
//   • Windows → `explorer <path>`.
//
// Slurmify is macOS-only for v0.2.0 but the Linux/Windows arms
// are kept for the eventual Phase 9 cross-platform port.

#[tauri::command]
fn reveal_in_finder(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("-R")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("failed to spawn `open -R`: {}", e))?;
    }
    #[cfg(target_os = "linux")]
    {
        Command::new("xdg-open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("failed to spawn `xdg-open`: {}", e))?;
    }
    #[cfg(target_os = "windows")]
    {
        Command::new("explorer")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("failed to spawn `explorer`: {}", e))?;
    }
    Ok(())
}

// ── Tauri app entry ───────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // ── Plugins ───────────────────────────────────────────────
        // Each plugin exposes a JS API under @tauri-apps/plugin-*.
        // Registered here so the frontend can import them; their
        // capabilities (read fs, spawn sidecar, etc.) are gated by
        // the capability files under src-tauri/capabilities/.
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())

        // ── Custom commands ────────────────────────────────────────
        // Each function annotated with #[tauri::command] becomes
        // callable from JS via `import { invoke } from "@tauri-apps/api/core"`.
        // Custom commands are auto-allowed when registered here in
        // Tauri 2 (no separate capability entry required).
        .invoke_handler(tauri::generate_handler![
            read_backend_discovery,
            reveal_in_finder,
        ])

        // ── Setup hook ────────────────────────────────────────────
        // Runs once after the window is created.
        .setup(|_app| {
            #[cfg(debug_assertions)]
            {
                println!("[slurmify-shell] Tauri 2 setup complete (debug)");
            }
            Ok(())
        })

        // ── Run ───────────────────────────────────────────────────
        .run(tauri::generate_context!())
        .expect("error while running slurmify Tauri app")
}
