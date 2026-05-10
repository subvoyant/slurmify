// ──────────────────────────────────────────────────────────────────────
// src/components/UtilityBar.tsx — Small toolbar above the slurm rack
// ──────────────────────────────────────────────────────────────────────
//
// Two utility actions ported from v0.1.6:
//
//   🎲 randomize all  — re-rolls every musical param to a randomly
//      chosen but musically-biased value.  Mirrors v0.1.6's
//      _randomize_all() in slurm_ui.py: speed in 0.5–3.0, resolution
//      from the full set including MAX RANDOM, pitch shift weighted
//      to musical intervals, etc.  Output format / source file /
//      seed are preserved (intentional choices the dice don't override).
//
//   📁 reveal temp  — opens the backend's session-scoped temp dir in
//      Finder so the user can grab any in-flight outputs before quit
//      wipes them (per the SIGTERM cleanup we just added).  Uses
//      Tauri's shell.open with a file:// URL for cross-platform
//      compatibility (works on macOS Finder, Windows Explorer,
//      Linux xdg-open).
//
// Future polish: the v0.1.6 hover gifs (Hoberman-Max for randomize,
// Bob for reveal) — slot these in as <img> assets when the user
// drops them into /public/ or /assets/.  For now we use Lucide icons
// so the buttons are functional + on-brand without art assets.
// ──────────────────────────────────────────────────────────────────────

import { useCallback } from "react"
import { Dices, FolderOpen, MessageSquare, Power, Sparkles } from "lucide-react"
import { invoke } from "@tauri-apps/api/core"
import { Button } from "@/components/ui/button"
import { Tip } from "@/components/ui/tooltip"
import { useSlurmStore, type SlurmParams } from "@/stores/slurmStore"
import { useUiPrefsStore } from "@/stores/uiPrefsStore"
import { getHealth } from "@/lib/api"
import { RESOLUTION_OPTIONS, type Resolution } from "@/components/ResolutionPicker"
import { EasterEggHover } from "@/components/EasterEggHover"
import { cn } from "@/lib/utils"

// ── Easter-egg gif imports ────────────────────────────────────────────
// Hoberman-Max springs up from the 🎲 randomize-all button (he's the
// roll-the-dice spirit animal); Bob springs up from the 📁 reveal-temp
// button (Bob suggested the feature in v0.1.6, so the easter egg is
// his thank-you).  Both are imported via Vite from the project's
// graphic/ folder — the build bundles them into hashed assets and
// the source files stay where they live.
import hobermanMaxGif from "../../graphic/hobermanmax.gif"
import bobGif         from "../../graphic/RGBOB.gif"

// ── randomize all — picks musically-biased random params ──────────────
// Direct port of v0.1.6's _randomize_all in slurm_ui.py.  Key bias
// rules preserved:
//   • speed in 0.5–3.0 (avoids the extreme 0.05–4.0 endpoints)
//   • pitch shift weighted to musical intervals (octaves, fifths)
//   • stutter_skip_ms weighted toward 0 + the 15-50ms zone
//   • stutter_max_reps weighted toward 4–8
//   • randomize_order forced TRUE when MAX RANDOM is selected (ADR-0013)

function rollSlurmParams(): Partial<SlurmParams> {
  const pick = <T,>(arr: readonly T[]): T => arr[Math.floor(Math.random() * arr.length)]
  const randInRange = (lo: number, hi: number) => lo + Math.random() * (hi - lo)
  const round       = (x: number, n = 2) => Math.round(x * 10 ** n) / 10 ** n

  const newRes = pick(RESOLUTION_OPTIONS) as Resolution

  // Beat trim / gap / beat mask / BPM override / seed / format are
  // NOT randomized — they're either workflow choices (format, seed)
  // or finer-grained params (trim/gap/mask) the v0.1.6 randomize-all
  // also leaves alone.  Intentionally matches v0.1.6 to keep output
  // character recognizable when users hit the dice.
  return {
    speed:                 round(randInRange(0.5, 3.0)),
    resolution:            newRes,
    transient_sensitivity: round(Math.random()),
    envelope_ms:           round(randInRange(0, 8), 1),
    preserve_pitch:        Math.random() < 0.7,
    pitch_shift_semitones: pick([-12, -7, -5, -3, 0, 0, 0, 3, 5, 7, 12]),
    randomize_order:       newRes === "MAX RANDOM" || Math.random() < 0.5,
    reverse_chance:        round(randInRange(0, 0.5)),
    stutter_chance:        round(randInRange(0, 0.5)),
    stutter_skip_ms:       pick([0, 0, 0, 10, 15, 20, 25, 30, 40, 50]),
    stutter_max_reps:      pick([2, 3, 4, 4, 6, 8]),
    stutter_spread:        round(randInRange(0, 0.6)),
  }
}

// ── Component ─────────────────────────────────────────────────────────

export function UtilityBar() {
  const setParam  = useSlurmStore((s) => s.setParam)
  const isRunning = useSlurmStore((s) => s.isRunning)
  // hasSource feeds the randomize-button enable state.  Pre-W5b the
  // whole UtilityBar was conditional on hasSource at the App.tsx
  // level — but now that this lives inside the always-visible TopBar
  // (so quit / tips / eggs / reveal-temp work even before a file is
  // loaded), we need to disable just the operations that don't make
  // sense without a source.  Reveal-temp is fine pre-source: the
  // session-temp dir exists from the moment the sidecar boots.
  const hasSource = useSlurmStore((s) => !!s.sourceFile)

  // UI-preferences toggles (tooltips on/off, easter eggs on/off).
  // Defaults are both true; reading + writing through Zustand so the
  // user's choice survives reloads via persist middleware.
  const tooltipsEnabled    = useUiPrefsStore((s) => s.tooltipsEnabled)
  const easterEggsEnabled  = useUiPrefsStore((s) => s.easterEggsEnabled)
  const setTooltipsEnabled = useUiPrefsStore((s) => s.setTooltipsEnabled)
  const setEasterEggsEnabled = useUiPrefsStore((s) => s.setEasterEggsEnabled)

  // Quit handler — fires the Tauri quit_app command which calls
  // `app.exit(0)` Rust-side, gracefully running the Exit event hook
  // (Python sidecar SIGTERM cleanup, plugin teardown).  Wrapped in a
  // confirm() so a stray click doesn't lose in-flight slurm state;
  // confirm is fine here, no extra modal infrastructure needed.
  const onQuit = useCallback(() => {
    if (isRunning) {
      const ok = confirm(
        "A slurmify job is running.  Quitting will abort it and discard the partial output.  Quit anyway?",
      )
      if (!ok) return
    }
    void invoke("quit_app").catch((e) => {
      console.error("[slurm] quit_app failed:", e)
      alert(`quit failed: ${(e as Error).message ?? e}`)
    })
  }, [isRunning])

  const onRandomize = useCallback(() => {
    if (isRunning) return
    const next = rollSlurmParams()
    // Apply each rolled field via setParam.  Cast each value through
    // SlurmParams[K] so TypeScript verifies field/value pairing.
    for (const key of Object.keys(next) as (keyof SlurmParams)[]) {
      setParam(key, next[key] as SlurmParams[typeof key])
    }
  }, [isRunning, setParam])

  const onRevealTemp = useCallback(async () => {
    try {
      const health = await getHealth()
      // Defensive: a backend running the OLD /health (pre-Phase E3a)
      // doesn't include tmp_dir.  Without this guard, JS would send
      // `{ path: undefined }` which JSON.stringify drops to `{}`,
      // and the Rust command would reject it as a missing key — a
      // confusing error.  Surface the real cause instead.
      if (!health.tmp_dir) {
        throw new Error(
          "backend /health did not include tmp_dir — restart the Python backend " +
          "(Ctrl-C the server.py terminal, then re-run it).  The new /health " +
          "endpoint added in v0.2.0 exposes the session temp directory.",
        )
      }
      // Bypass Tauri's plugin-shell scope plumbing — invoke our own
      // Rust command (src-tauri/src/lib.rs reveal_in_finder) which
      // spawns `open -R <path>` directly.  Rust has unrestricted
      // process-spawn from inside the app, so no scope config is
      // needed.  See ADR-0022 §6.2 for the pattern.
      await invoke("reveal_in_finder", { path: health.tmp_dir })
    } catch (e) {
      console.error("[slurm] failed to reveal temp dir:", e)
      // Surface the error visibly — without a toast system yet, an
      // alert() is the cheapest "user sees the problem" UI.  W5 polish
      // replaces this with a proper toast component.
      alert(`reveal temp failed: ${(e as Error).message ?? e}`)
    }
  }, [])

  // Note on layout: this component used to live in its own row, hence
  // its outer flex container.  After W5b it sits inside <TopBar>
  // alongside <PresetBar>; we set `flex-1` so this group expands to
  // fill all the space PresetBar didn't claim, which lets the
  // internal `ml-auto` on the tips/eggs/quit cluster push those
  // controls to the rightmost edge of the WHOLE bar (not just the
  // rightmost edge of UtilityBar).
  return (
    <div className="flex flex-1 items-center gap-2">
      {/* Hoberman-Max springs up from below the 🎲 randomize button —
          v0.1.6 gif sized 145×120 (landscape).  Same bouncy
          cubic-bezier as Bob for visual consistency between the two
          utility buttons. */}
      <EasterEggHover
        gifSrc={hobermanMaxGif}
        width={145}
        height={120}
        anchor="spring-up"
        alt="Hoberman-Max bouncing"
      >
        <Tip
          text={
            <span>
              🎲 <strong>randomize all</strong> — re-rolls every musical
              param (speed, resolution, transient, envelope, pitch,
              shuffle, reverse, stutter family) using the same
              distributions as v0.1.6.  Source file, output format,
              and seed are preserved.
            </span>
          }
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={onRandomize}
            // Disabled while a slurm is in flight (would race the live
            // params) AND when no source file is loaded (no point
            // randomising knobs that aren't connected to anything yet).
            disabled={isRunning || !hasSource}
          >
            <Dices />
            randomize
          </Button>
        </Tip>
      </EasterEggHover>

      {/* Bob rises from the TOP-RIGHT of the SLICING module.  Portal-
          mode + alignToSelector pins his BOTTOM edge to the SLICING
          rack's top edge, and `alignXSide="right"` parks him over
          the right portion of the rack (above the beat-mask chip
          strip) instead of being centered on the reveal-temp button
          way over in the utility bar.  Visual effect: Bob pops up
          out of the gap between the input rack and the slicing
          rack's header, on the right side, like he's been hiding
          behind the rack and just leaned out for a look.  The cache-
          bust on every hover restarts his GIF from frame 1. */}
      <EasterEggHover
        gifSrc={bobGif}
        width={75}
        height={274}
        anchor="spring-up"
        usePortal
        alignToSelector='section[data-rack-name="slicing"]'
        alignXSide="right"
        alt="Bob waving hello"
      >
        <Tip
          text={
            <span>
              📁 <strong>reveal temp files</strong> — opens the backend's
              session-scoped temp directory in Finder.  Useful for grabbing
              slurm outputs before they're auto-wiped on quit.  Files you
              export elsewhere (drag-out, save-as) are unaffected.
            </span>
          }
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={onRevealTemp}
          >
            <FolderOpen />
            reveal temp
          </Button>
        </Tip>
      </EasterEggHover>

      {/* ── UI-prefs toggles + quit ───────────────────────────────────
          Pushed to the right via ml-auto so the action-style controls
          (randomize, reveal) stay anchored on the LEFT and the
          UI-mode switches + the quit button cluster on the RIGHT.
          Visual mode of each toggle: when ON the icon button uses
          the primary accent (text-primary, ring on focus); when OFF
          the icon goes to muted text and the button reads as
          quieter — same treatment as a depressed pedal switch on a
          guitar amp. */}
      <div className="ml-auto flex items-center gap-1.5">
        <Tip
          text={
            <span>
              <strong>tooltips {tooltipsEnabled ? "on" : "off"}</strong>{" "}
              — toggle every hover-help bubble globally.  Useful for
              clean screen recordings or once you've memorized the
              controls.  Re-enable any time; setting persists across
              reloads.
            </span>
          }
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setTooltipsEnabled(!tooltipsEnabled)}
            aria-pressed={tooltipsEnabled}
            className={cn(
              tooltipsEnabled
                ? "text-primary hover:text-primary"
                : "text-slurm-muted",
            )}
          >
            <MessageSquare />
            {tooltipsEnabled ? "tips on" : "tips off"}
          </Button>
        </Tip>

        <Tip
          text={
            <span>
              <strong>easter eggs {easterEggsEnabled ? "on" : "off"}</strong>{" "}
              — toggle Bob, Max, MaxFire, and Hoberman-Max globally.
              When off, hover gifs are short-circuited entirely (no
              GIF preload, no portal).  Recommended for clean
              recordings; toggle back on for everyday use.
            </span>
          }
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setEasterEggsEnabled(!easterEggsEnabled)}
            aria-pressed={easterEggsEnabled}
            className={cn(
              easterEggsEnabled
                ? "text-primary hover:text-primary"
                : "text-slurm-muted",
            )}
          >
            <Sparkles />
            {easterEggsEnabled ? "eggs on" : "eggs off"}
          </Button>
        </Tip>

        <Tip
          text={
            <span>
              <strong>quit</strong> — close Slurmify cleanly.  Fires
              Tauri's exit hook so the Python backend gets a SIGTERM
              and wipes its session-temp directory before the process
              ends.  In-flight slurms are aborted; export anything
              you want to keep BEFORE quitting (or use 📁 reveal temp
              to grab files first).
            </span>
          }
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={onQuit}
            className="text-slurm-muted hover:text-slurm-danger"
          >
            <Power />
            quit
          </Button>
        </Tip>
      </div>
    </div>
  )
}
