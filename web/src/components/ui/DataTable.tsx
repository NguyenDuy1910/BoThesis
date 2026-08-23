"use client";

import { cn } from "@/lib/cn";
import { ChevronDown, ChevronUp, Inbox } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

export interface Column<T> {
  key: string;
  label: string;
  sortable?: boolean;
  className?: string;
  width?: number | string;
  minWidth?: number;
  align?: "left" | "center" | "right";
  resizable?: boolean;
  render?: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyField?: string;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => React.ReactNode;
  className?: string;
  density?: "dense" | "default" | "comfortable";
  selectable?: boolean;
  selectedRowIds?: string[];
  onSelectedRowIdsChange?: (ids: string[]) => void;
  getRowId?: (row: T) => string;
  stickyHeader?: boolean;
}

const densityClasses = {
  dense: {
    row: "h-9",
    head: "px-3 py-2",
    cell: "px-3 py-1.5",
  },
  default: {
    row: "h-11",
    head: "px-3 py-2.5",
    cell: "px-3 py-2",
  },
  comfortable: {
    row: "h-12",
    head: "px-4 py-3",
    cell: "px-4 py-2.5",
  },
};

const alignClasses = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  keyField = "id",
  emptyMessage = "No data found",
  onRowClick,
  rowActions,
  className,
  density = "default",
  selectable = false,
  selectedRowIds,
  onSelectedRowIdsChange,
  getRowId,
  stickyHeader = true,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [internalSelectedIds, setInternalSelectedIds] = useState<string[]>([]);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({});

  const selectedIds = selectedRowIds ?? internalSelectedIds;
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const setSelectedIds = useCallback(
    (ids: string[]) => {
      if (onSelectedRowIdsChange) {
        onSelectedRowIdsChange(ids);
      } else {
        setInternalSelectedIds(ids);
      }
    },
    [onSelectedRowIdsChange]
  );

  const rowId = useCallback(
    (row: T) => (getRowId ? getRowId(row) : String(row[keyField])),
    [getRowId, keyField]
  );

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedData = sortKey
    ? [...data].sort((a, b) => {
        const aVal = a[sortKey];
        const bVal = b[sortKey];
        if (aVal == null) return 1;
        if (bVal == null) return -1;
        const cmp = String(aVal).localeCompare(String(bVal), undefined, {
          numeric: true,
          sensitivity: "base",
        });
        return sortDir === "asc" ? cmp : -cmp;
      })
    : data;

  const visibleIds = sortedData.map(rowId);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedSet.has(id));
  const someVisibleSelected = visibleIds.some((id) => selectedSet.has(id));
  const densityClass = densityClasses[density];

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      setSelectedIds(selectedIds.filter((id) => !visibleIds.includes(id)));
      return;
    }

    setSelectedIds(Array.from(new Set([...selectedIds, ...visibleIds])));
  };

  const toggleRow = (id: string) => {
    setSelectedIds(
      selectedSet.has(id)
        ? selectedIds.filter((selectedId) => selectedId !== id)
        : [...selectedIds, id]
    );
  };

  const handleResizeStart = useCallback(
    (key: string, event: React.PointerEvent<HTMLSpanElement>) => {
      event.preventDefault();
      event.stopPropagation();

      const headerCell = event.currentTarget.closest("th");
      const startWidth = columnWidths[key] ?? headerCell?.getBoundingClientRect().width ?? 160;
      const startX = event.clientX;

      const handleMove = (moveEvent: PointerEvent) => {
        const nextWidth = Math.max(72, startWidth + moveEvent.clientX - startX);
        setColumnWidths((prev) => ({ ...prev, [key]: nextWidth }));
      };

      const handleUp = () => {
        document.removeEventListener("pointermove", handleMove);
        document.removeEventListener("pointerup", handleUp);
      };

      document.addEventListener("pointermove", handleMove);
      document.addEventListener("pointerup", handleUp);
    },
    [columnWidths]
  );

  const resizeColumnWithKeyboard = useCallback(
    (key: string, direction: -1 | 1, currentWidth: number | string | undefined) => {
      const fallbackWidth = typeof currentWidth === "number" ? currentWidth : 160;
      const nextWidth = Math.max(72, (columnWidths[key] ?? fallbackWidth) + direction * 16);
      setColumnWidths((prev) => ({ ...prev, [key]: nextWidth }));
    },
    [columnWidths]
  );

  if (data.length === 0) {
    return (
      <div className={cn("flex min-h-40 flex-col items-center justify-center border-y border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center text-sm text-[var(--text-muted)]", className)}>
        <span className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded-md bg-[var(--primary-soft)] text-[var(--brand-accent)] ring-1 ring-inset ring-[var(--border)]">
          <Inbox aria-hidden="true" className="h-4 w-4" />
        </span>
        <span className="font-medium text-[var(--text)]">{emptyMessage}</span>
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto border-y border-[var(--border)] bg-[var(--surface)]", className)}>
      <table className="w-full min-w-full border-separate border-spacing-0 text-sm">
        <thead className={cn("bg-[var(--bg-panel)]", stickyHeader && "sticky top-0 z-[1]")}>
          <tr className="border-b border-[var(--border)]">
            {selectable && (
              <th className="w-10 border-b border-[var(--border)] px-3 py-2 text-left">
                <input
                  aria-checked={someVisibleSelected && !allVisibleSelected ? "mixed" : allVisibleSelected}
                  aria-label="Select all visible rows"
                  type="checkbox"
                  checked={allVisibleSelected}
                  data-indeterminate={someVisibleSelected && !allVisibleSelected ? "true" : undefined}
                  ref={(input) => {
                    if (input) input.indeterminate = someVisibleSelected && !allVisibleSelected;
                  }}
                  onChange={toggleAllVisible}
                  className="h-4 w-4 rounded border-[var(--border-strong)] text-[var(--brand-accent)] focus:ring-[var(--focus-ring)]"
                />
              </th>
            )}
            {columns.map((col) => {
              const width = columnWidths[col.key] ?? col.width;
              const style = {
                width,
                minWidth: col.minWidth ?? width,
              };

              return (
                <th
                  aria-sort={col.sortable && sortKey === col.key ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
                  key={col.key}
                  className={cn(
                    "group relative whitespace-nowrap border-b border-[var(--border)] text-xs font-semibold text-[var(--text-muted)]",
                    alignClasses[col.align ?? "left"],
                    densityClass.head,
                    col.className
                  )}
                  style={style}
                  scope="col"
                >
                  {col.sortable ? (
                    <button
                      className="inline-flex items-center gap-1.5 rounded-sm transition-colors hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                      onClick={() => handleSort(col.key)}
                      type="button"
                    >
                      {col.label}
                      {sortKey === col.key && (
                        sortDir === "asc" ? <ChevronUp aria-hidden="true" className="h-3 w-3" /> : <ChevronDown aria-hidden="true" className="h-3 w-3" />
                      )}
                    </button>
                  ) : (
                    <span>{col.label}</span>
                  )}
                  {col.resizable !== false && (
                    <span
                      aria-label={`Resize ${col.label} column`}
                      aria-orientation="vertical"
                      className="absolute right-0 top-1/2 h-5 w-1 -translate-y-1/2 cursor-col-resize rounded-full bg-transparent transition-colors group-hover:bg-[var(--border-strong)] focus-visible:bg-[var(--brand-accent)] focus-visible:outline-none"
                      onKeyDown={(event) => {
                        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                        event.preventDefault();
                        resizeColumnWithKeyboard(col.key, event.key === "ArrowLeft" ? -1 : 1, width);
                      }}
                      onPointerDown={(event) => handleResizeStart(col.key, event)}
                      role="separator"
                      tabIndex={0}
                    />
                  )}
                </th>
              );
            })}
            {rowActions && (
              <th className="sticky right-0 w-32 min-w-32 border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-right text-xs font-semibold text-[var(--text-muted)]">
                Actions
              </th>
            )}
          </tr>
        </thead>
        <tbody className="bg-[var(--surface)]">
          {sortedData.map((row) => {
            const id = rowId(row);
            const selected = selectedSet.has(id);

            return (
              <tr
                aria-selected={selectable ? selected : undefined}
                key={id}
                className={cn(
                  "border-b border-[var(--border)] transition-colors last:border-b-0",
                  densityClass.row,
                  selected && "bg-[var(--surface-selected)]",
                  onRowClick && "cursor-pointer hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]"
                )}
                onClick={() => onRowClick?.(row)}
                onKeyDown={(event) => {
                  if (!onRowClick || (event.key !== "Enter" && event.key !== " ")) return;
                  event.preventDefault();
                  onRowClick(row);
                }}
                tabIndex={onRowClick ? 0 : undefined}
              >
                {selectable && (
                  <td className="border-b border-[var(--border)] px-3 py-2" onClick={(event) => event.stopPropagation()}>
                    <input
                      aria-label={`Select row ${id}`}
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleRow(id)}
                      className="h-4 w-4 rounded border-[var(--border-strong)] text-[var(--brand-accent)] focus:ring-[var(--focus-ring)]"
                    />
                  </td>
                )}
                {columns.map((col) => {
                  const width = columnWidths[col.key] ?? col.width;
                  const style = {
                    width,
                    minWidth: col.minWidth ?? width,
                  };

                  return (
                    <td
                      key={col.key}
                      className={cn(
                        "border-b border-[var(--border)] align-middle text-sm text-[var(--text-secondary)]",
                        alignClasses[col.align ?? "left"],
                        densityClass.cell,
                        col.className
                      )}
                      style={style}
                    >
                      {col.render ? col.render(row) : String(row[col.key] ?? "")}
                    </td>
                  );
                })}
                {rowActions && (
                  <td
                    className={cn("sticky right-0 w-32 min-w-32 border-b border-[var(--border)] bg-[var(--surface)] text-right", densityClass.cell)}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {rowActions(row)}
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
