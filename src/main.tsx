// ──────────────────────────────────────────────────────────────────────
// src/main.tsx — React 19 entrypoint
// ──────────────────────────────────────────────────────────────────────
//
// The Vite + Tauri scaffold mounts <App/> into the <div id="root"> in
// index.html.  This file stays tiny by design — anything that has
// state, side-effects, or business logic belongs in App.tsx or its
// children, not here.
// ──────────────────────────────────────────────────────────────────────

import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { App } from "./App"
import { TooltipProvider } from "./components/ui/tooltip"

// Tailwind directives + skin CSS variables.  Imported once here so the
// styles are bundled into the entry chunk and apply globally.
import "./styles/globals.css"

const root = document.getElementById("root")
if (!root) {
  // Should never happen — index.html owns the div.  If it does, fail
  // loudly so we notice during development rather than silently
  // booting a blank window.
  throw new Error("missing #root in index.html")
}

createRoot(root).render(
  <StrictMode>
    {/* TooltipProvider supplies the shared timing + portal context for
        every <Tip> in the app.  delayDuration matches macOS's native
        ~300ms tooltip delay; skipDelayDuration lets adjacent tooltips
        re-show instantly after the user has already triggered one. */}
    <TooltipProvider delayDuration={300} skipDelayDuration={100}>
      <App />
    </TooltipProvider>
  </StrictMode>,
)
