"use client";

import { BookOpen, ChevronDown, ChevronRight, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * One node in a knowledge hierarchy — a source, or a collection inside it.
 *
 * Only used inside a temporary Browse popover. The hierarchy is never a
 * permanent rail: horizontal space belongs to the documents.
 */
export function TreeNode({
  label,
  count,
  depth = 0,
  open = false,
  selected = false,
  icon: Icon = BookOpen,
  onToggle,
  onSelect,
}: {
  label: string;
  count: number;
  depth?: number;
  open?: boolean;
  selected?: boolean;
  icon?: LucideIcon;
  onToggle?: () => void;
  onSelect?: () => void;
}) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div
      className={cn(
        "flex w-full min-w-0 items-center gap-1.5 rounded-[var(--radius-sm)] pr-2.5",
        selected ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
      style={{ paddingLeft: 6 + depth * 16 }}
    >
      <button
        aria-expanded={open}
        aria-label={open ? `Collapse ${label}` : `Expand ${label}`}
        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[var(--radius-xs)] text-[var(--text-tertiary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        onClick={onToggle}
        type="button"
      >
        <Chevron aria-hidden="true" size={14} />
      </button>
      <button
        className={cn(
          "flex min-w-0 flex-1 items-center gap-1.5 rounded-[var(--radius-sm)] py-1.5 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        )}
        onClick={onSelect}
        type="button"
      >
        <Icon
          aria-hidden="true"
          className={cn("shrink-0", selected ? "text-[var(--text-accent)]" : "text-[var(--text-tertiary)]")}
          size={18}
        />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)]",
            selected ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]",
          )}
        >
          {label}
        </span>
        <span className="shrink-0 text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
          {count.toLocaleString()}
        </span>
      </button>
    </div>
  );
}
