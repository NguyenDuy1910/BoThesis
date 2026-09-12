"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { cn } from "@/lib/cn";

export interface Column<T> {
  key: string;
  label: string;
  sortable?: boolean;
  className?: string;
  width?: number | string;
  minWidth?: number;
  align?: "left" | "right";
  /**
   * How hard a column fights for space. `high` is always shown, `medium` is
   * dropped on phones and `low` only survives on wide screens — so a narrow
   * viewport loses detail columns instead of pushing status off the edge.
   * Defaults to `high`.
   */
  priority?: "high" | "medium" | "low";
  /**
   * The column that takes the leftover width and truncates. Defaults to the
   * first column, which is the record's name on every list in the console.
   */
  primary?: boolean;
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField?: string;
  getRowId?: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Rendered in a trailing cell that reveals on row hover and focus. */
  rowActions?: (row: T) => React.ReactNode;
  selectable?: boolean;
  selectedRowIds?: string[];
  onSelectedRowIdsChange?: (ids: string[]) => void;
  emptyState?: React.ReactNode;
  className?: string;
  ariaLabel?: string;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField = "id",
  getRowId,
  onRowClick,
  rowActions,
  selectable = false,
  selectedRowIds,
  onSelectedRowIdsChange,
  emptyState,
  className,
  ariaLabel,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [internalSelected, setInternalSelected] = useState<string[]>([]);

  const selectedIds = selectedRowIds ?? internalSelected;
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const rowId = useCallback(
    (row: T) => (getRowId ? getRowId(row) : String(row[keyField])),
    [getRowId, keyField],
  );

  const setSelected = useCallback(
    (ids: string[]) => {
      if (onSelectedRowIdsChange) onSelectedRowIdsChange(ids);
      else setInternalSelected(ids);
    },
    [onSelectedRowIdsChange],
  );

  const sorted = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (left == null) return 1;
      if (right == null) return -1;
      const comparison = String(left).localeCompare(String(right), undefined, {
        numeric: true,
        sensitivity: "base",
      });
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [data, sortDirection, sortKey]);

  if (!data.length) return <>{emptyState}</>;

  const primaryKey =
    columns.find((column) => column.primary)?.key ?? columns[0]?.key;

  const responsiveClass = (column: Column<T>) =>
    column.priority === "low"
      ? "hidden xl:table-cell"
      : column.priority === "medium"
        ? "hidden md:table-cell"
        : undefined;

  const visibleIds = sorted.map(rowId);
  const allSelected = visibleIds.every((id) => selectedSet.has(id));
  const someSelected = !allSelected && visibleIds.some((id) => selectedSet.has(id));

  return (
    <div className={cn("adm-table-wrap", className)}>
      <table aria-label={ariaLabel} className="adm-table">
        <thead>
          <tr>
            {selectable && (
              <th className="w-9" scope="col">
                <input
                  aria-label="Select every row"
                  checked={allSelected}
                  className="h-3.5 w-3.5 cursor-pointer accent-[var(--text-accent)]"
                  onChange={() =>
                    setSelected(
                      allSelected
                        ? selectedIds.filter((id) => !visibleIds.includes(id))
                        : Array.from(new Set([...selectedIds, ...visibleIds])),
                    )
                  }
                  ref={(input) => {
                    if (input) input.indeterminate = someSelected;
                  }}
                  type="checkbox"
                />
              </th>
            )}
            {columns.map((column) => (
              <th
                aria-sort={
                  column.sortable && sortKey === column.key
                    ? sortDirection === "asc"
                      ? "ascending"
                      : "descending"
                    : undefined
                }
                className={cn(
                  column.align === "right" && "adm-table__num",
                  responsiveClass(column),
                  column.key === primaryKey && "adm-table__primary",
                  column.className,
                )}
                key={column.key}
                scope="col"
                style={{ width: column.width, minWidth: column.minWidth }}
              >
                {column.sortable ? (
                  <button
                    // Negative margin plus matching padding makes the whole
                    // header cell the hit area instead of just the label.
                    className="-mx-3.5 -my-2 inline-flex items-center gap-1 px-3.5 py-2 transition-colors hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]"
                    onClick={() => {
                      if (sortKey === column.key) {
                        setSortDirection(sortDirection === "asc" ? "desc" : "asc");
                      } else {
                        setSortKey(column.key);
                        setSortDirection("asc");
                      }
                    }}
                    type="button"
                  >
                    {column.label}
                    {sortKey === column.key &&
                      (sortDirection === "asc" ? (
                        <ChevronUp aria-hidden="true" className="h-3 w-3" />
                      ) : (
                        <ChevronDown aria-hidden="true" className="h-3 w-3" />
                      ))}
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
            {rowActions && (
              <th className="adm-table__actions-cell" scope="col">
                <span className="sr-only">Row actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const id = rowId(row);
            const selected = selectedSet.has(id);
            return (
              <tr
                data-clickable={onRowClick ? "true" : undefined}
                data-selected={selected ? "true" : undefined}
                key={id}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key !== "Enter") return;
                        event.preventDefault();
                        onRowClick(row);
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
              >
                {selectable && (
                  <td onClick={(event) => event.stopPropagation()}>
                    <input
                      aria-label="Select row"
                      checked={selected}
                      className="h-3.5 w-3.5 cursor-pointer accent-[var(--text-accent)]"
                      onChange={() =>
                        setSelected(
                          selected
                            ? selectedIds.filter((value) => value !== id)
                            : [...selectedIds, id],
                        )
                      }
                      type="checkbox"
                    />
                  </td>
                )}
                {columns.map((column) => (
                  <td
                    className={cn(
                      column.align === "right" && "adm-table__num",
                      responsiveClass(column),
                      column.key === primaryKey && "adm-table__primary",
                      column.className,
                    )}
                    key={column.key}
                    style={{ width: column.width, minWidth: column.minWidth }}
                  >
                    {column.render
                      ? column.render(row)
                      : String(row[column.key] ?? "—")}
                  </td>
                ))}
                {rowActions && (
                  <td
                    className="adm-table__actions-cell"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <div className="adm-table__actions">{rowActions(row)}</div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Primary cell content: a name with one line of supporting detail. */
export function CellTitle({
  title,
  subtitle,
  icon,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {icon}
      <span className="min-w-0">
        <span className="block truncate font-medium text-[var(--text-primary)]">{title}</span>
        {subtitle && (
          <span className="block truncate text-[0.75rem] text-[var(--text-tertiary)]">
            {subtitle}
          </span>
        )}
      </span>
    </div>
  );
}
