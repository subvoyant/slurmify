// ──────────────────────────────────────────────────────────────────────
// src/components/PresetBar.tsx — Top-of-app preset dropdown + save/delete
// ──────────────────────────────────────────────────────────────────────
//
// One slim row above the rack modules:
//
//   ┌───────────────────────────────────────────────────────────────┐
//   │ preset:  [▾ 2× canonical (modified) ]   [+ save as…]   [✕]    │
//   └───────────────────────────────────────────────────────────────┘
//
// Behavior:
//   • The dropdown lists factory presets first, then a divider, then
//     user presets in insertion order.  Selecting one applies it to
//     slurmStore.params (per-file fields preserved).
//   • "(modified)" appears next to the active preset's name when the
//     live params differ from the saved data.  Drives users to save
//     their tweaks before switching.
//   • [+ save as…] expands into a small inline textbox: type a name,
//     hit Enter to save, Escape to cancel.  Names that collide with
//     factory ids are rejected with a tooltip explanation.
//   • [✕] only appears when a USER preset is selected — factory
//     presets are read-only.
//
// Layout choice — placed above the rack stack rather than inside
// any single rack so the user can grab a flavor and watch ALL
// modules update in unison, rather than associating presets with one
// particular rack.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import { Plus, Trash2, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tip } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

import {
  FACTORY_PRESETS,
  FACTORY_PRESET_IDS,
} from "@/lib/factory-presets"
import {
  usePresetStore,
  isPresetModified,
  type ActivePresetId,
} from "@/stores/presetStore"
import { useSlurmStore } from "@/stores/slurmStore"

// Encoded select-value for the dropdown.  Radix Select wants string
// values; we serialize/deserialize ActivePresetId here.  Format is
// `factory:{id}` or `user:{name}`.  Empty/sentinel = "(none)".
const NONE_VALUE = "__none__"
function encode(active: ActivePresetId): string {
  if (active === null) return NONE_VALUE
  return active.kind === "factory" ? `factory:${active.id}` : `user:${active.name}`
}
function decode(v: string): ActivePresetId {
  if (v === NONE_VALUE) return null
  if (v.startsWith("factory:")) return { kind: "factory", id: v.slice("factory:".length) }
  if (v.startsWith("user:"))    return { kind: "user", name: v.slice("user:".length) }
  return null
}

export function PresetBar() {
  const userPresets    = usePresetStore((s) => s.userPresets)
  const activePresetId = usePresetStore((s) => s.activePresetId)
  const applyPreset    = usePresetStore((s) => s.applyPreset)
  const savePreset     = usePresetStore((s) => s.savePreset)
  const deletePreset   = usePresetStore((s) => s.deletePreset)

  const liveParams = useSlurmStore((s) => s.params)
  const modified   = isPresetModified(activePresetId, liveParams)

  // ── Save-as inline textbox ────────────────────────────────────────
  const [saveOpen, setSaveOpen] = React.useState(false)
  const [saveName, setSaveName] = React.useState("")
  const [saveError, setSaveError] = React.useState<string | null>(null)
  const saveInputRef = React.useRef<HTMLInputElement | null>(null)

  // Auto-focus the textbox when it opens.  Without this the user has
  // to click into it before typing, which feels broken on a button-
  // triggered field.
  React.useEffect(() => {
    if (saveOpen) saveInputRef.current?.focus()
  }, [saveOpen])

  const handleSave = () => {
    const name = saveName.trim()
    if (!name) {
      setSaveError("name cannot be empty")
      return
    }
    if (FACTORY_PRESET_IDS.has(name)) {
      setSaveError(`"${name}" is reserved — pick a different name`)
      return
    }
    // Overwrite confirmation — only when stomping on an existing
    // user preset (factory case is already blocked above).
    if (name in userPresets) {
      const ok = window.confirm(
        `Overwrite existing preset "${name}"?  The previous version will be lost.`,
      )
      if (!ok) return
    }
    try {
      savePreset(name)
      setSaveOpen(false)
      setSaveName("")
      setSaveError(null)
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  const handleSaveKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleSave()
    } else if (e.key === "Escape") {
      e.preventDefault()
      setSaveOpen(false)
      setSaveName("")
      setSaveError(null)
    }
  }

  const handleDelete = () => {
    if (activePresetId?.kind !== "user") return
    const name = activePresetId.name
    const ok = window.confirm(`Delete preset "${name}"?  This cannot be undone.`)
    if (ok) deletePreset(name)
  }

  // Build the display string for the trigger.  When a preset is
  // selected and modified, append "(modified)" so the user knows
  // their tweaks aren't captured.
  const triggerLabel = (() => {
    if (activePresetId === null) return "(none)"
    if (activePresetId.kind === "factory") {
      const fp = FACTORY_PRESETS.find((p) => p.id === activePresetId.id)
      return fp?.name ?? "(missing)"
    }
    return activePresetId.name
  })()

  // Sorted user preset names — insertion order from the object.  Keys
  // ordering on plain objects is reliable in modern JS for string
  // keys, so this matches save order without an explicit array.
  const userPresetNames = Object.keys(userPresets)

  return (
    <div
      className={cn(
        "flex items-center gap-2",
        "rounded border border-slurm-border bg-slurm-surface",
        "px-3 py-2",
        "text-[11px]",
      )}
    >
      <Tip
        text={
          <>
            Saved slurmify <strong>flavors</strong> — speed, resolution,
            knob values, note-mode toggles, output format. Per-file
            settings (in/out trim, beat mask, BPM override, seed)
            are NOT saved in a preset; they stay tied to the loaded
            file.
          </>
        }
      >
        <span className="text-slurm-muted cursor-help select-none uppercase tracking-[0.15em]">
          preset
        </span>
      </Tip>

      <Select
        value={encode(activePresetId)}
        onValueChange={(v) => applyPreset(decode(v))}
      >
        <SelectTrigger className="h-7 w-[220px] !text-[11px]">
          <SelectValue>
            <span className="truncate">
              {triggerLabel}
              {modified && (
                <span className="ml-1 text-slurm-warn">(modified)</span>
              )}
            </span>
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {/* "(none)" reset option — clears the active selection
              without changing params. */}
          <SelectItem value={NONE_VALUE} className="text-[11px]">
            <span className="text-slurm-muted">(none)</span>
          </SelectItem>

          {/* Factory group */}
          <SelectGroup>
            <SelectLabel className="text-[10px] uppercase tracking-wider text-slurm-muted">
              factory
            </SelectLabel>
            {FACTORY_PRESETS.map((p) => (
              <SelectItem
                key={`factory:${p.id}`}
                value={`factory:${p.id}`}
                className="text-[11px]"
              >
                <span className="flex items-baseline gap-2">
                  <span>{p.name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectGroup>

          {/* User group — only render the divider + label when there
              are any user presets to list (avoids an empty section). */}
          {userPresetNames.length > 0 && (
            <>
              <SelectSeparator />
              <SelectGroup>
                <SelectLabel className="text-[10px] uppercase tracking-wider text-slurm-muted">
                  yours
                </SelectLabel>
                {userPresetNames.map((name) => (
                  <SelectItem
                    key={`user:${name}`}
                    value={`user:${name}`}
                    className="text-[11px]"
                  >
                    {name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </>
          )}
        </SelectContent>
      </Select>

      {/* Save As — toggles inline textbox.  Closed by default to
          keep the bar compact. */}
      {!saveOpen ? (
        <Tip text="Capture the current slurmify settings under a name. Per-file values (in/out, BPM override, beat mask, seed) are NOT saved.">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px]"
            onClick={() => setSaveOpen(true)}
          >
            <Plus className="!h-3 !w-3" />
            save as…
          </Button>
        </Tip>
      ) : (
        <div className="flex items-center gap-1">
          <Input
            ref={saveInputRef}
            value={saveName}
            onChange={(e) => {
              setSaveName(e.target.value)
              setSaveError(null)
            }}
            onKeyDown={handleSaveKeyDown}
            placeholder="preset name"
            className="!h-7 w-[160px] !text-[11px]"
          />
          <Tip text="Save (or press Enter)">
            <Button
              size="sm"
              variant="default"
              className="h-7 px-2 text-[11px]"
              onClick={handleSave}
            >
              save
            </Button>
          </Tip>
          <Tip text="Cancel (or press Escape)">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0"
              onClick={() => {
                setSaveOpen(false)
                setSaveName("")
                setSaveError(null)
              }}
            >
              <X className="!h-3 !w-3" />
            </Button>
          </Tip>
          {saveError && (
            <span className="text-[10px] text-slurm-danger ml-1">
              {saveError}
            </span>
          )}
        </div>
      )}

      {/* Delete — ONLY visible when a user preset is selected. */}
      {activePresetId?.kind === "user" && !saveOpen && (
        <Tip text={`Delete preset "${activePresetId.name}". Cannot be undone.`}>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0 text-slurm-muted hover:text-slurm-danger"
            onClick={handleDelete}
          >
            <Trash2 className="!h-3 !w-3" />
          </Button>
        </Tip>
      )}

      {/* "Update" button when active preset is modified — saves over
          the current preset without prompting for a new name.  Only
          relevant for user presets (factory presets are read-only;
          the user has to "save as" a copy). */}
      {modified && activePresetId?.kind === "user" && !saveOpen && (
        <Tip text={`Save current settings into "${activePresetId.name}", overwriting the previous version.`}>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px] text-slurm-warn hover:text-slurm-fg"
            onClick={() => {
              try {
                savePreset(activePresetId.name)
              } catch (e) {
                window.alert((e as Error).message)
              }
            }}
          >
            update
          </Button>
        </Tip>
      )}
    </div>
  )
}
