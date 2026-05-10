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
use std::sync::Mutex;
use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

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

// ── quit_app ──────────────────────────────────────────────────────────
// Gracefully shut the whole app down: triggers Tauri's standard exit
// path, which runs the `RunEvent::Exit` hook (where the SIGTERM cleanup
// for the Python sidecar is wired — see ADR-0022 §6.4) before the
// process ends.  Calling `app.exit(0)` instead of `std::process::exit`
// is the documented way to do this in Tauri 2; it lets registered
// event handlers run and gives plugins (shell, fs, dialog) a chance
// to finalize.
//
// Frontend invokes via `await invoke("quit_app")` from the QUIT
// button in UtilityBar.  No return value — the JS Promise will never
// resolve because the process is gone before the response is sent.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    // Kill the bundled Python sidecar BEFORE Tauri's own exit path
    // runs.  Doing it here (in addition to the RunEvent::Exit hook)
    // covers the case where a quick app.exit(0) doesn't always fire
    // RunEvent::Exit synchronously — a missing kill leaves an orphan
    // python process bound to the discovery port.
    kill_sidecar(&app);
    app.exit(0);
}

// ── Sidecar lifecycle ─────────────────────────────────────────────────
// Phase D: start the bundled Python backend at app launch and shut it
// down at exit.  Replaces the v0.2.0-dev "user runs python in a
// separate terminal" flow.
//
// Wiring:
//   1. tauri.conf.json's `bundle.externalBin` lists
//      "binaries/slurmify-backend"; the build step copies the
//      PyInstaller bundle (renamed to slurmify-backend-<triple>) into
//      Contents/MacOS/ of the .app at `pnpm tauri build` time.
//   2. capabilities/default.json grants the shell plugin
//      `shell:allow-spawn` for that exact binary.
//   3. setup() below runs in the Tauri event loop right after the
//      window is created.  It calls `shell().sidecar("slurmify-backend")`
//      which resolves to the bundled binary at runtime, spawns it,
//      and reads stdout line-by-line.
//   4. The first stdout line that parses as
//        {"slurmify_ready": true, "port": NNNNN}
//      is captured; we emit a "backend-ready" event with the port for
//      the frontend's useBackend hook to pick up.
//   5. The CommandChild handle is stashed in a Mutex<Option<...>> on
//      app state so RunEvent::Exit (and quit_app above) can reach it
//      to kill on shutdown.
//
// In dev mode (`debug_assertions` set) we DO NOT spawn the sidecar —
// the developer runs `python src-python/server.py` in a terminal
// alongside `pnpm tauri dev`, and the existing read_backend_discovery
// path picks up the port from the discovery file.  Detecting "are we
// dev or production" via cfg is cleaner than a runtime env-var check.

/// Mutex-wrapped child handle so we can safely send a kill signal
/// from anywhere (RunEvent::Exit hook OR a quit_app frontend call).
#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

/// Try to kill the sidecar if it's running.  Idempotent — calling
/// twice is fine (the second call sees None and exits silently).
fn kill_sidecar(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(child) = guard.take() {
                let pid = child.pid();
                eprintln!("[slurmify-shell] killing sidecar pid={}", pid);
                let _ = child.kill();
            }
        }
    }
}

/// Spawn the PyInstaller-bundled FastAPI sidecar.  Called from the
/// setup() hook in production (release) builds; in dev builds we
/// short-circuit and rely on the developer's manual `python
/// src-python/server.py` terminal.
fn spawn_sidecar(app: &tauri::AppHandle) -> Result<(), String> {
    // Nuke any stale discovery file from a previous instance BEFORE
    // we start the new sidecar.  Why: server.py's atexit handler
    // unlinks the file on clean shutdown, but a crash or a user
    // closing the .app via Force Quit leaves the file behind pointing
    // at a now-dead port.  When THIS instance's frontend boots, its
    // useBackend hook calls read_backend_discovery, gets the stale
    // port, /health probes it, gets nothing, and the upload UI shows
    // "network error" forever.
    //
    // Deleting up-front means worst-case the frontend sees "no
    // discovery file yet" for a few hundred ms while the new sidecar
    // boots and writes its own — useBackend's 2-s poll handles that
    // gracefully and shows "checking…" until the new file appears.
    let stale = env::temp_dir().join(DISCOVERY_FILENAME);
    if stale.exists() {
        match fs::remove_file(&stale) {
            Ok(_)  => eprintln!("[slurmify-shell] cleared stale discovery file at {}", stale.display()),
            Err(e) => eprintln!("[slurmify-shell] WARN: could not remove stale {}: {}", stale.display(), e),
        }
    }

    let sidecar = app
        .shell()
        .sidecar("slurmify-backend")
        .map_err(|e| format!("could not resolve sidecar: {}", e))?;

    let (mut rx, child) = sidecar
        .spawn()
        .map_err(|e| format!("could not spawn sidecar: {}", e))?;

    eprintln!("[slurmify-shell] sidecar spawned, pid={}", child.pid());

    // Stash the child handle so we can kill it on shutdown.
    if let Some(state) = app.try_state::<SidecarState>() {
        if let Ok(mut guard) = state.0.lock() {
            *guard = Some(child);
        }
    }

    // Read stdout/stderr in a background task.  We're looking for the
    // ready-line JSON; everything else is logged for diagnostics.  The
    // sidecar's logs continue to flow through this loop for the whole
    // lifetime of the process — useful when something goes wrong in
    // production and we need to see Python's traceback.
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    eprintln!("[sidecar/out] {}", line.trim_end());
                    // Try to parse a ready-line JSON payload; emit on
                    // success.  Any non-JSON stdout line is just a log
                    // line — we don't error.
                    if let Ok(parsed) =
                        serde_json::from_str::<SidecarReady>(line.trim())
                    {
                        if parsed.slurmify_ready {
                            eprintln!(
                                "[slurmify-shell] backend ready on port {}",
                                parsed.port
                            );
                            let _ = app_handle.emit("backend-ready", parsed.port);
                        }
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    eprintln!("[sidecar/err] {}", line.trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    eprintln!(
                        "[slurmify-shell] sidecar terminated (code={:?}, signal={:?})",
                        payload.code, payload.signal
                    );
                }
                CommandEvent::Error(err) => {
                    eprintln!("[slurmify-shell] sidecar error: {}", err);
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Shape of the JSON line server.py prints when uvicorn binds.  Must
/// match write_discovery_file()'s ready-line in src-python/server.py.
#[derive(Deserialize, Debug)]
struct SidecarReady {
    slurmify_ready: bool,
    port:           u16,
}

// ── Tauri app entry ───────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // ── Plugins ───────────────────────────────────────────────
        // Each plugin exposes a JS API under @tauri-apps/plugin-*.
        // Registered here so the frontend can import them; their
        // capabilities (read fs, spawn sidecar, etc.) are gated by
        // the capability files under src-tauri/capabilities/.
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())

        // ── App state ─────────────────────────────────────────────
        // SidecarState holds the spawned Python process handle so
        // we can SIGTERM it from RunEvent::Exit AND from the
        // quit_app command.  Default is empty — populated when the
        // setup hook spawns the sidecar.
        .manage(SidecarState::default())

        // ── Custom commands ────────────────────────────────────────
        // Each function annotated with #[tauri::command] becomes
        // callable from JS via `import { invoke } from "@tauri-apps/api/core"`.
        // Custom commands are auto-allowed when registered here in
        // Tauri 2 (no separate capability entry required).
        .invoke_handler(tauri::generate_handler![
            read_backend_discovery,
            reveal_in_finder,
            quit_app,
        ])

        // ── Setup hook ────────────────────────────────────────────
        // Runs once after the window is created.
        //   • Production builds spawn the bundled Python sidecar.
        //   • Dev builds (debug_assertions) skip the spawn — the
        //     developer runs `python src-python/server.py` manually
        //     in a separate terminal, and read_backend_discovery
        //     picks up the port via the discovery file.
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                println!(
                    "[slurmify-shell] Tauri 2 setup complete (debug). \
                     Sidecar NOT auto-spawned — run \
                     `python src-python/server.py` manually."
                );
            }

            #[cfg(not(debug_assertions))]
            {
                let handle = app.handle().clone();
                if let Err(e) = spawn_sidecar(&handle) {
                    eprintln!(
                        "[slurmify-shell] failed to spawn sidecar: {}.  \
                         The frontend will sit at \"waiting for backend\" \
                         until restart.",
                        e
                    );
                }
            }

            // Suppress the unused-variable lint in dev builds where
            // we never reach the production-only branch above.
            let _ = app;
            Ok(())
        })

        // ── Build (deferred run) ──────────────────────────────────
        // Build the app instead of run()-ing it inline so we can
        // attach a custom RunEvent handler below.  The handler is
        // where SidecarState's child gets killed on shutdown.
        .build(tauri::generate_context!())
        .expect("error while building slurmify Tauri app");

    // ── Custom run loop with RunEvent::Exit hook ──────────────────
    // Tauri fires RunEvent::Exit right before the process is torn
    // down (window closed, Cmd-Q, app.exit() called).  This is the
    // last chance to clean up the spawned sidecar — without it, the
    // python child orphans and keeps holding its bound port until
    // manually killed (or the OS reaps it on user logout).
    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            kill_sidecar(app_handle);
        }
    });
}
