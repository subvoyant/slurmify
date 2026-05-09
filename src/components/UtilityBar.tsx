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
import { Dices, FolderOpen } from "lucide-react"
import { invoke } from "@tauri-apps/api/core"
import { Button } from "@/components/ui/button"
import { Tip } from "@/components/ui/tooltip"
import { useSlurmStore, type SlurmParams } from "@/stores/slurmStore"
import { getHealth } from "@/lib/api"
import { RESOLUTION_OPTIONS, type Resolution } from "@/components/ResolutionPicker"
import { EasterEggHover } from "@/components/EasterEggHover"

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

  return (
    <div className="flex items-center gap-2">
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
            disabled={isRunning}
          >
            <Dices />
            randomize
          </Button>
        </Tip>
      </EasterEggHover>

      {/* Bob springs up from below the 📁 reveal-temp button — v0.1.6
          gif sized 75×274 (tall portrait).  Bob suggested the
          reveal-temp feature so he gets the easter egg. */}
      <EasterEggHover
        gifSrc={bobGif}
        width={75}
        height={274}
        anchor="spring-up"
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
    </div>
  )
}
