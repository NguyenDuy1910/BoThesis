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

  if (data.length === 0) {
    return (
      <div className={cn("flex min-h-40 flex-col items-center justify-center border-y border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-600", className)}>
        <span className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded-md bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-200">
          <Inbox className="h-4 w-4" />
        </span>
        <span className="font-medium text-slate-800">{emptyMessage}</span>
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto border-y border-slate-200 bg-white", className)}>
      <table className="w-full min-w-full border-separate border-spacing-0 text-sm">
        <thead className={cn("bg-slate-50", stickyHeader && "sticky top-0 z-[1]")}> 
          <tr className="border-b border-slate-200">
            {selectable && (
              <th className="w-10 border-b border-slate-200 px-3 py-2 text-left">
                <input
                  aria-label="Select all visible rows"
                  type="checkbox"
                  checked={allVisibleSelected}
                  data-indeterminate={someVisibleSelected && !allVisibleSelected ? "true" : undefined}
                  onChange={toggleAllVisible}
                  className="h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-500/20"
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
                  key={col.key}
                  className={cn(
                    "group relative whitespace-nowrap border-b border-slate-200 text-xs font-semibold text-slate-500",
                    alignClasses[col.align ?? "left"],
                    densityClass.head,
                    col.sortable && "cursor-pointer select-none hover:text-slate-900",
                    col.className
                  )}
                  onClick={() => col.sortable && handleSort(col.key)}
                  style={style}
                  scope="col"
                >
                  <span className="inline-flex items-center gap-1.5">
                    {col.label}
                    {col.sortable && sortKey === col.key && (
                      sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                    )}
                  </span>
                  {col.resizable !== false && (
                    <span
                      aria-hidden="true"
                      className="absolute right-0 top-1/2 h-5 w-1 -translate-y-1/2 cursor-col-resize rounded-full bg-transparent transition group-hover:bg-slate-300"
                      onPointerDown={(event) => handleResizeStart(col.key, event)}
                    />
                  )}
                </th>
              );
            })}
            {rowActions && (
              <th className="sticky right-0 w-32 min-w-32 border-b border-slate-200 bg-slate-50 px-3 py-2 text-right text-xs font-semibold text-slate-500">
                Actions
              </th>
            )}
          </tr>
        </thead>
        <tbody className="bg-white">
          {sortedData.map((row) => {
            const id = rowId(row);
            const selected = selectedSet.has(id);

            return (
              <tr
                key={id}
                className={cn(
                  "border-b border-slate-100 transition-colors last:border-b-0",
                  densityClass.row,
                  selected && "bg-teal-50/45",
                  onRowClick && "cursor-pointer hover:bg-slate-50"
                )}
                onClick={() => onRowClick?.(row)}
              >
                {selectable && (
                  <td className="border-b border-slate-100 px-3 py-2" onClick={(event) => event.stopPropagation()}>
                    <input
                      aria-label={`Select row ${id}`}
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleRow(id)}
                      className="h-4 w-4 rounded border-slate-300 text-teal-700 focus:ring-teal-500/20"
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
                        "border-b border-slate-100 align-middle text-sm text-slate-700",
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
                    className={cn("sticky right-0 w-32 min-w-32 border-b border-slate-100 bg-white text-right", densityClass.cell)}
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
