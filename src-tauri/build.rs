// ──────────────────────────────────────────────────────────────────────
// src-tauri/build.rs — Tauri 2 build script
// ──────────────────────────────────────────────────────────────────────
// Required by tauri-build to wire up icons, code-gen the bundle config,
// and emit the resource files Tauri needs at runtime.  Standard
// boilerplate — don't edit unless you know why.
// ──────────────────────────────────────────────────────────────────────

fn main() {
    tauri_build::build()
}
