// ──────────────────────────────────────────────────────────────────────
// src/components/SkinPicker.tsx — small <select> bound to skinStore
// ──────────────────────────────────────────────────────────────────────
//
// Phase C2 keeps this minimal — a native <select> styled to fit the
// dark theme.  Phase D / W5 polish may upgrade to a shadcn Popover +
// preview swatches if it's worth the real-estate.
// ──────────────────────────────────────────────────────────────────────

import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { useSkinStore, SKIN_OPTIONS, type Skin } from "@/stores/skinStore"

export function SkinPicker() {
  const { skin, setSkin } = useSkinStore()

  return (
    <Tip
      text={
        <>
          Switch the visual skin. Module identity colors (each rack
          panel's header) stay stable across skins, but the body
          tints + waveform colors + slider styling all retint.{" "}
          <strong>default</strong> = subvoyant cyan-on-charcoal.{" "}
          <strong>acid cathedral</strong> = mint + hot-pink
          psychedelic.{" "}
          <strong>hardware rack</strong> = LED-amber-on-black with
          monospace type.
        </>
      }
    >
      <label
        className={cn(
          "flex items-center gap-2 text-xs text-slurm-muted",
          "select-none",
        )}
      >
        <span className="uppercase tracking-[0.15em]">skin</span>
        <select
          value={skin}
          onChange={(e) => setSkin(e.target.value as Skin)}
          className={cn(
            "rounded-md border border-slurm-border bg-slurm-surface",
            "px-2 py-1 text-xs text-slurm-fg",
            "focus:outline-none focus:ring-1 focus:ring-slurm-cyan",
            "cursor-pointer hover:bg-slurm-surface2",
            "transition-colors",
          )}
        >
          {SKIN_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
    </Tip>
  )
}
