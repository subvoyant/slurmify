// ──────────────────────────────────────────────────────────────────────
// src/components/ui/select.tsx — Radix Select, themed
// ──────────────────────────────────────────────────────────────────────
//
// Standard shadcn Select on top of Radix's accessible primitive.
// Used for the output format dropdown in the OUTPUT module.  Phase
// E3's resolution picker uses a chip row instead — Select is for
// long-list dropdowns where chip rows would overflow.
//
// Usage (composable parts pattern, mirrors shadcn's docs):
//   <Select value={format} onValueChange={setFormat}>
//     <SelectTrigger><SelectValue placeholder="format" /></SelectTrigger>
//     <SelectContent>
//       <SelectItem value="wav">WAV</SelectItem>
//       <SelectItem value="mp3">MP3</SelectItem>
//     </SelectContent>
//   </Select>
//
// The Content portal renders into <body> by default which Tauri 2's
// webview handles correctly.  We pass position="popper" to anchor
// against the trigger.
// ──────────────────────────────────────────────────────────────────────

import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

const Select = SelectPrimitive.Root
const SelectGroup = SelectPrimitive.Group
const SelectValue = SelectPrimitive.Value

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-7 w-full items-center justify-between gap-2",
      "rounded border border-slurm-border bg-slurm-surface px-2 py-1",
      "text-[12px] text-slurm-fg",
      "ring-offset-slurm-bg",
      "placeholder:text-slurm-muted",
      "focus:outline-none focus:ring-1 focus:ring-slurm-cyan",
      "disabled:cursor-not-allowed disabled:opacity-50",
      "[&>span]:line-clamp-1",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-3.5 w-3.5 opacity-60" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
))
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-50 min-w-[8rem] overflow-hidden",
        "rounded border border-slurm-border bg-slurm-surface text-slurm-fg",
        "shadow-md",
        "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
        "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        position === "popper" && [
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1",
          "data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        ],
        className,
      )}
      position={position}
      {...props}
    >
      <SelectPrimitive.Viewport className="p-1">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
))
SelectContent.displayName = SelectPrimitive.Content.displayName

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-default select-none items-center",
      "rounded px-2 py-1 text-[12px] outline-none",
      "focus:bg-slurm-surface2 focus:text-slurm-fg",
      "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      "pr-7",
      className,
    )}
    {...props}
  >
    <span className="absolute right-1.5 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-3 w-3" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
))
SelectItem.displayName = SelectPrimitive.Item.displayName

// SelectLabel — non-interactive heading for a SelectGroup ("FACTORY",
// "YOURS").  Visually styled like the rack module subtle labels.
const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn(
      "px-2 py-1.5 text-[10px] font-mono uppercase tracking-[0.15em]",
      "text-slurm-muted select-none",
      className,
    )}
    {...props}
  />
))
SelectLabel.displayName = SelectPrimitive.Label.displayName

// SelectSeparator — thin divider between groups (e.g. between
// factory and user presets).
const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-slurm-border", className)}
    {...props}
  />
))
SelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectLabel,
  SelectSeparator,
}
