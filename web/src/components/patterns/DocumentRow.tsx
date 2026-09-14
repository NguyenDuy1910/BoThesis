"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";
import { StatusPill, type StatusTone } from "./StatusPill";

const DOT: Record<StatusTone, string> = {
  neutral: "bg-[var(--status-neutral-solid)]",
  success: "bg-[var(--status-success-solid)]",
  info: "bg-[var(--status-info-solid)]",
  warning: "bg-[var(--status-warning-solid)]",
  danger: "bg-[var(--status-danger-solid)]",
  accent: "bg-[var(--accent-primary)]",
};

/**
 * One document.
 *
 * `full` is the standalone list — status pill and updated column. `narrow` is
 * the split-view list beside a viewer, where the columns collapse to a single
 * status dot so the name keeps its measure. Selecting a row opens the viewer;
 * it never navigates away.
 */
export function DocumentRow({
  icon: Icon,
  title,
  meta,
  status,
  statusTone = "success",
  updated,
  layout = "full",
  selected = false,
  onSelect,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  meta: string;
  status?: string;
  statusTone?: StatusTone;
  updated?: string;
  layout?: "full" | "narrow";
  selected?: boolean;
  onSelect?: () => void;
  actions?: React.ReactNode;
}) {
  const narrow = layout === "narrow";
  return (
    <div
      className={cn(
        "group flex w-full min-w-0 items-center rounded-[var(--radius-sm)]",
        narrow ? "gap-2.5" : "gap-3",
        selected ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
    >
      <button
        className={cn(
          "flex min-w-0 flex-1 items-center rounded-[var(--radius-sm)] text-left",
          narrow ? "gap-2.5 px-2.5 py-2.5" : "gap-3 px-3 py-2.5",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        )}
        onClick={onSelect}
        type="button"
      >
        <Icon aria-hidden="true" className="shrink-0 text-[var(--text-tertiary)]" size={narrow ? 20 : 22} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
            {title}
          </span>
          <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {meta}
          </span>
        </span>
        {narrow && status && (
          <span aria-label={status} className={cn("h-[7px] w-[7px] shrink-0 rounded-full", DOT[statusTone])} />
        )}
        {!narrow && status && <StatusPill tone={statusTone}>{status}</StatusPill>}
        {!narrow && updated && (
          <span className="shrink-0 text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {updated}
          </span>
        )}
      </button>
      {actions && (
        <span className="shrink-0 pr-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {actions}
        </span>
      )}
    </div>
  );
}
