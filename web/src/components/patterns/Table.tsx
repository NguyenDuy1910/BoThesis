"use client";

import { cn } from "@/lib/cn";

export interface TableColumn {
  id: string;
  label: string;
  /** Fixed px width; omit for the one column that takes the remaining space. */
  width?: number;
}

/**
 * Column labels for a control-plane table.
 *
 * Tables are correct here — this is bulk comparison across tenants or people,
 * not an end-user surface.
 */
export function TableHeader({ columns, leading }: { columns: readonly TableColumn[]; leading?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-5 border-b border-[var(--border-subtle)] px-3.5 pb-2.5">
      {leading}
      {columns.map((column) => (
        <div
          className={cn(
            "text-[length:var(--text-size-caption)] font-medium uppercase tracking-[var(--text-tracking-caption)] text-[var(--text-tertiary)]",
            column.width === undefined && "min-w-0 flex-1",
          )}
          key={column.id}
          style={column.width === undefined ? undefined : { width: column.width, flexShrink: 0 }}
        >
          {column.label}
        </div>
      ))}
      <div className="w-[4.5rem] shrink-0" />
    </div>
  );
}

/**
 * One row. Actions appear on hover only; clicking the row opens the contextual
 * detail panel rather than navigating away, so the list stays in view.
 */
export function TableRow({
  selected = false,
  onSelect,
  actions,
  children,
}: {
  selected?: boolean;
  onSelect?: () => void;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "group flex items-center rounded-[var(--radius-sm)]",
        selected ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
    >
      {onSelect ? (
        <button
          className={cn(
            "flex min-w-0 flex-1 items-center gap-5 rounded-[var(--radius-sm)] px-3.5 py-2.5 text-left",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
          )}
          onClick={onSelect}
          type="button"
        >
          {children}
        </button>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-5 px-3.5 py-2.5 text-left">
          {children}
        </div>
      )}
      <span className="w-[4.5rem] shrink-0 pr-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {actions}
      </span>
    </div>
  );
}

/** A cell inside a TableRow; widths mirror the header's columns. */
export function TableCell({
  width,
  children,
  className,
}: {
  width?: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "truncate text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-secondary)]",
        width === undefined && "min-w-0 flex-1",
        className,
      )}
      style={width === undefined ? undefined : { width, flexShrink: 0 }}
    >
      {children}
    </div>
  );
}
