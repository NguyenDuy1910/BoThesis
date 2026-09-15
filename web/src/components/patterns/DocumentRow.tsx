"use client";

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
 *
 * The leading checkbox only materialises on hover, on focus, or once a
 * selection exists, so a resting list is not covered in controls. It is always
 * in the DOM — a control that appears on hover cannot be reached by keyboard.
 */
export function DocumentRow({
  icon,
  title,
  meta,
  status,
  statusTone = "success",
  updated,
  layout = "full",
  selected = false,
  onSelect,
  actions,
  checked,
  onCheckedChange,
}: {
  icon: React.ReactNode;
  title: string;
  meta: string;
  status?: string;
  statusTone?: StatusTone;
  updated?: string;
  layout?: "full" | "narrow";
  selected?: boolean;
  onSelect?: () => void;
  actions?: React.ReactNode;
  /** Omit both to render a list that cannot be selected in bulk. */
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
}) {
  const narrow = layout === "narrow";
  const selectable = Boolean(onCheckedChange);
  return (
    <div
      className={cn(
        "document-row group flex w-full min-w-0 items-center rounded-[var(--radius-sm)]",
        narrow ? "gap-1" : "gap-2",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        selected || checked ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
    >
      {selectable && (
        <input
          aria-label={`Select ${title}`}
          checked={checked ?? false}
          className="document-row__select ml-3 h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--accent-primary)]"
          onChange={(event) => onCheckedChange?.(event.target.checked)}
          type="checkbox"
        />
      )}
      <button
        aria-current={selected ? "true" : undefined}
        className={cn(
          "flex min-w-0 flex-1 items-center rounded-[var(--radius-sm)] text-left",
          narrow ? "gap-2.5 px-2.5 py-2.5" : "gap-3 px-3 py-2.5",
          selectable && "pl-2",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
        )}
        onClick={onSelect}
        type="button"
      >
        <span className="shrink-0">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
            {title}
          </span>
          <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {meta}
          </span>
        </span>
        {status && narrow && (
          <>
            <span aria-hidden="true" className={cn("h-[7px] w-[7px] shrink-0 rounded-full", DOT[statusTone])} />
            <span className="sr-only">{status}</span>
          </>
        )}
        {status && !narrow && <StatusPill tone={statusTone}>{status}</StatusPill>}
        {updated && !narrow && (
          <span className="document-row__updated w-14 shrink-0 text-right text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {updated}
          </span>
        )}
      </button>
      {actions && (
        <span className="shrink-0 pr-1.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          {actions}
        </span>
      )}
    </div>
  );
}
