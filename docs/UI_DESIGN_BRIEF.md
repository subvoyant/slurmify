# UI Design Brief — Slurmify v0.2.0

**Status:** Living document · v0.2.0 baseline · May 2026
**Audience:** anyone building UI in this codebase
**Scope:** every component decision from Phase D onward

---

## 1. Goal in one sentence

A native macOS audio app that looks like a hardware unit, not a web form.

## 2. The problem we're escaping

Gradio v0.1.6 had real ergonomic issues that Phase D-onward must NOT
inherit. Documenting them here so the contrast is concrete.

| Gradio anti-pattern | What's wrong | What we do instead |
|---|---|---|
| Every slider in its own padded card | Vertical waste; controls feel disconnected | Inline labels + tight rows; group related controls in flat panels |
| 16-24px padding inside every component | Half the screen is whitespace, not signal | 6-10px panel padding, 4-8px row gap |
| Big rounded corners (8-12px) on every box | Web aesthetic, not desktop-app aesthetic | 4-6px corners only; sharp where it matters |
| Heavy borders on every control | Borders fight each other | Borders ONLY at panel edges, never around individual controls |
| Stacked single-column layouts | Wastes horizontal real estate on a 1280×860 window | Horizontal flow + multi-column where it makes sense |
| Verbose `info=` text below every label | 80% of the visible text is meta-instruction | Tooltips on demand; only show essential help inline |
| Big sliders with separate label and value | Three lines per slider | One row: label · slider · value · unit toggle |
| Generous line-heights | Reads like a form, not a control panel | Tight (1.3-1.4) for body, normal (1.5) for prose |

## 3. Reference aesthetics

Look at these when designing new components:

- **Reason Studios' rack devices (PRIMARY REFERENCE)** — Dr.OctoRex,
  Thor, Ripley, Mimic, Umpf, ST-1.  Color-coded panels, brand label
  on the right edge, tiny LCD-amber readouts, density without
  noise.  Slurmify v0.2.0 should feel like a Reason rack: a vertical
  stack of self-identifying modules, each with personality.  See §9
  for the rack-module pattern this is the basis of.
- **u-he plugin UIs** (Diva, Repro, Hive) — dark, dense, every pixel
  doing work. No empty padding for breathing room — controls touch.
- **Valhalla DSP plugins** — minimal chrome, big knobs, subtle
  inter-control separators rather than per-control borders.
- **Ableton Live's clip detail view** — multi-column control grids,
  tiny labels above tiny controls, lots happening in 200px height.
- **Splice sample editor** — clean waveform-first layout; controls are
  secondary chrome around the audio surface, not the focus.
- **iA Writer** — typography discipline. One typeface, two sizes,
  mostly the same color. Hierarchy via weight + position, not boxes.

Stay AWAY from:
- shadcn/ui's reference site itself (too web-form-y; we use the
  primitives but theme them tighter).
- GitHub / Linear / Notion (knowledge-tool aesthetic — too breezy).
- Material Design's defaults (Material is for Android forms, not
  desktop creative tools).

## 4. Concrete numeric rules

### Spacing scale (Tailwind tokens we actually use)

| Use | Tailwind token | Pixels | Notes |
|---|---|---|---|
| Tight inline gap (label-to-value, icon-to-text) | `gap-1.5` | 6px | |
| Default control row gap | `gap-2` | 8px | |
| Inter-group gap inside a panel | `gap-3` | 12px | |
| Between top-level panels | `gap-4` | 16px | |
| Outer page padding | `p-4` | 16px | |
| Panel internal padding | `p-2` to `p-3` | 8-12px | NOT 16+ |
| Form-row vertical padding | `py-1` to `py-1.5` | 4-6px | |

NEVER use `gap-6`, `gap-8`, `p-6`, `p-8` for routine UI. Reserve those
for hero sections / empty-state placeholders.

### Border-radius

| Use | Token | Pixels |
|---|---|---|
| Panels, cards | `rounded-md` | 6px (matches `--radius`) |
| Buttons, inputs | `rounded` | 4px |
| Pill-shaped status indicators | `rounded-full` | full |
| **Avoid** `rounded-lg`, `rounded-xl` for routine UI | — | — |

### Typography scale

| Use | Tailwind | Pixels | Line-height |
|---|---|---|---|
| Default body / control labels | `text-[13px]` | 13px | 1.4 |
| Compact metadata / hints | `text-[11px]` | 11px | 1.4 |
| Section headings | `text-[12px] uppercase tracking-[0.15em]` | 12px | 1.2 |
| Display values (big knob readouts) | `text-base font-mono` | 16px | 1 |
| Page-level h1 (the SIENA SLURMER title) | `text-lg font-extralight tracking-[0.2em]` | 18px | 1 |

NEVER use `text-base` (16px) or `text-sm` (14px) as the default body.
Default in shadcn-land is too big for our context.

### Borders

- **Panels:** `border border-slurm-border` (one weight, on the panel only).
- **Form rows inside a panel:** no border. Use background color
  variation or a hairline `border-t border-slurm-border-2` ONLY between
  groups, not between every row.
- **Inputs (slider tracks, dropdowns):** `border-slurm-border` at rest;
  `ring-1 ring-slurm-cyan` on focus. No box-shadow defaults.

### Color usage

- **Primary actions** (Slurmify, Burn FX, Render): `--slurm-cyan`
  (or its skin equivalent). One per panel max.
- **Secondary actions** (Reset, Cancel): muted secondary. No color
  emphasis.
- **Destructive** (delete, quit): red. Sparingly.
- **Status colors** (ok/warn/danger): use `--slurm-ok`, `--slurm-warn`,
  `--slurm-danger`. Never reach for raw hex in components.
- **Text:** default `text-slurm-fg` (foreground). `text-slurm-muted`
  for hints/metadata. Avoid hand-written gray hex values.

## 5. Layout patterns

### Form rows

A control row is a single horizontal flex line:

```
┌─────────────────────────────────────────────────────────┐
│ stutter skip · [────●───────────] · 30 ms · [ms / ♪]   │
└─────────────────────────────────────────────────────────┘
```

Markup pattern:

```tsx
<div className="flex items-center gap-3 py-1">
  <label className="w-32 shrink-0 text-[13px] text-slurm-muted">
    stutter skip
  </label>
  <Slider className="flex-1" {...} />
  <span className="w-16 shrink-0 text-right text-[13px] tabular-nums">
    {ms} ms
  </span>
  <UnitToggle ... />
</div>
```

Three rules:
1. Label has fixed width (so multiple rows align).
2. Slider takes flex-1 (eats the rest).
3. Value has fixed width + `tabular-nums` so digits don't shift.

### Panels

A panel is a `border + bg-slurm-surface + rounded-md` container with
a small header bar. Inside, a vertical stack of form rows with no
inner borders:

```
┌───────────────────────────────────────────┐
│  STUTTER                          1/3     │  ← header
├───────────────────────────────────────────┤
│  chance     [────●────]  0.4              │
│  skip       [────●────]  30 ms · ms ♪     │
│  reps max   [────●────]  4                │
│  spread     [────●────]  0.0              │
└───────────────────────────────────────────┘
```

Header text: 11px uppercase, muted. The "1/3" on the right is the
"step number" if relevant — pure decoration, optional.

### Multi-column

Slurm controls naturally split into 2-3 columns at full window width:

```
┌─ trim ──────────┐  ┌─ stretch ──────┐  ┌─ stutter ─────┐
│  start 0 ms     │  │  speed 2.0×    │  │  chance 0.4   │
│  end   0 ms     │  │  pitch 0       │  │  skip   30ms  │
│  gap   0 ms     │  │  preserve  ☑   │  │  reps   4     │
└─────────────────┘  └────────────────┘  └───────────────┘
```

Each column is a panel. Use Tailwind's `grid grid-cols-3 gap-4`.

## 9. The Rack Module pattern (PRIMARY visual structure)

Every major control group in Slurmify is a "rack module" — a self-
contained unit modeled on Reason's rack devices.  Vertical stack of
modules fills the main content area; each module is visually distinct
so the user can locate functionality at a glance.

### Anatomy

```
┌─────────────────────────────────────────────────────────────────┐
│ ●  I N P U T                                          SLURM ─ ┤  ← header
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────┐   filename.wav                  │
│  │ drop file or click          │   3:23 · stereo · 44.1kHz       │  ← body
│  │       to upload             │   [▶] ━━━━━━━●━━━━ 1:14         │
│  └────────────────────────────┘                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Header (32px tall)

- **Status dot on the left** — 8px circle, color = module's identity
  color (orange for I/O, teal for slicing, blue for FX, etc.).  When
  the module is "active" (e.g., a job is running), the dot pulses.
- **Module name** — tracked-out uppercase, 11-12px, on the colored
  header background.  e.g., `I N P U T`, `S L I C I N G`,
  `S T U T T E R`, `F X`, `O U T P U T`.
- **Brand strip on the right** — 1-2px tall colored bar + small
  "SLURM" wordmark in the panel's identity color.  Sells the
  module-as-product feel.

### Body

- **Single panel, no inner cards.**  Form rows directly inside the
  body using §5's row pattern.  Inset shadow at top to suggest
  depth.
- **Padding:** 8-12px on all sides.  No more.
- **Background:** `--slurm-surface` for the body, with the header
  in a slightly different (slightly desaturated) tone of the
  module's identity color.

### Module identity colors

| Module | Identity color | Inspiration |
|---|---|---|
| **I N P U T** (source upload + waveform) | warm orange `#c47a2c` | Dr.OctoRex |
| **S L I C I N G** (resolution + transient + bpm) | teal `#2c7c8c` | Thor blue |
| **S T R E T C H** (speed + pitch + preserve) | warm sand `#a08855` | Mimic beige |
| **B E A T  T R I M** (per-slice trim + gap) | rose `#a05a6a` | hardware accent |
| **S T U T T E R** (chance, skip, reps, spread) | red-orange `#bc4a30` | classic stutter danger |
| **F X** (distortion → ring → delay → phaser) | deep blue `#3a5a90` | Ripley |
| **O U T P U T** (slurmify button + format + render video) | LED green `#3a8c4a` | tape-record green |

These colors are constants used ONLY for header backgrounds and
status dots.  They do NOT change per skin — the rack identity is
stable, only the body colors re-tint with the active skin.  This
mirrors Reason: a Thor in dark mode is still teal-headered.

### Vertical rhythm

Modules stack with `gap-2` (8px) between them.  No outer container
padding.  The window becomes a continuous rack from top header to
bottom render button.

### Code pattern

A reusable `<RackModule>` component — header takes `name`, `color`,
`status?`; children fill the body.  Implementing in Phase D1.

```tsx
<RackModule name="INPUT" color="rgb(196 122 44)" status="ready">
  <DropZone />
</RackModule>
```

## 6. Phase-by-phase application

| Phase | What this brief changes |
|---|---|
| **Phase D** (DropZone + waveform) | DropZone is a single small drop region, not a giant card; waveform is the focal element with minimal chrome. |
| **W3** (slurm controls) | Multi-column panel layout per §5; form rows per §5; no per-control borders. |
| **W4** (FX chain + skins) | FX panel is a single dense rack; rotary knobs eventually replace sliders for FX (but slider rows are fine for first pass). |
| **W5** (video export + polish) | Polish pass — verify every component conforms to §4 and §5. |

## 7. What changes when we deviate

Sometimes a stricter native-app aesthetic doesn't serve a particular
control. When we deviate from this brief, document why in a comment in
the component file. Examples of legitimate deviations:

- Drag-and-drop targets: NEED visible boundary even when idle, so
  `border-2 border-dashed` is OK (deviation from §4).
- Disabled / "coming soon" states: may use lighter borders + opacity
  to communicate the state without removing the control entirely.
- Empty-state hero text: gets bigger type because it IS the focus
  during that moment.

When we accidentally backslide toward Gradio-feel padding and chrome,
expect a comment in code review pointing at this brief.

## 8. Updating this brief

This is a LIVING document. When a component decision yields a pattern
worth reusing, add it to §5. When we find a numeric rule from §4 too
tight or too loose, update the table — but update every existing
component to match.

The brief is the rules; the components are the rules made real.
Drift between them is a sign we should update one or the other.
