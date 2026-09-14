"use client";

import { Search } from "lucide-react";

import { Card } from "@/components/ui/Card";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Pagination } from "@/components/ui/Pagination";
import { TableSkeleton } from "@/components/ui/Skeleton";

interface ResourceListProps<T extends Record<string, unknown>> {
  columns: Column<T>[];
  rows: T[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** Shown when the resource genuinely has no records yet. */
  empty: React.ReactNode;
  /** Shown when filters hide everything — offers a way back, not a dead end. */
  onClearFilters?: () => void;
  filtersActive?: boolean;
  ariaLabel: string;
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => React.ReactNode;
  toolbar?: React.ReactNode;
  /** Rendered above the table when rows are selected. */
  bulkBar?: React.ReactNode;
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
  };
  selectable?: boolean;
  /** The row an open inspector is describing. */
  activeRowId?: string | null;
  selectedRowIds?: string[];
  onSelectedRowIdsChange?: (ids: string[]) => void;
}

/**
 * The shared shape of every list screen in the console: toolbar, one card, one
 * table, one pagination footer, and the same four states in the same order.
 * Pages describe their data; they do not re-lay-out the page around it.
 */
export function ResourceList<T extends Record<string, unknown>>({
  columns,
  rows,
  loading,
  error,
  onRetry,
  empty,
  onClearFilters,
  filtersActive = false,
  ariaLabel,
  onRowClick,
  rowActions,
  toolbar,
  bulkBar,
  pagination,
  activeRowId,
  selectable,
  selectedRowIds,
  onSelectedRowIdsChange,
}: ResourceListProps<T>) {
  if (error) {
    return (
      <ErrorState
        actionLabel="Try again"
        description={error}
        onAction={onRetry}
        title={`${ariaLabel} could not be loaded`}
      />
    );
  }

  return (
    <>
      {toolbar && <div className="adm-toolbar">{toolbar}</div>}
      {bulkBar}
      <Card>
        {loading ? (
          <TableSkeleton columns={Math.min(columns.length, 5)} />
        ) : rows.length === 0 ? (
          filtersActive ? (
            <EmptyState
              action={
                onClearFilters && (
                  <button
                    className="text-[length:var(--text-size-ui)] font-medium text-[var(--text-accent)] underline-offset-4 hover:underline"
                    onClick={onClearFilters}
                    type="button"
                  >
                    Clear filters
                  </button>
                )
              }
              description="No records match the current search and filters."
              icon={<Search className="h-5 w-5" />}
              title="Nothing matches"
            />
          ) : (
            empty
          )
        ) : (
          <>
            <DataTable
              activeRowId={activeRowId}
              ariaLabel={ariaLabel}
              columns={columns}
              data={rows}
              onRowClick={onRowClick}
              onSelectedRowIdsChange={onSelectedRowIdsChange}
              rowActions={rowActions}
              selectable={selectable}
              selectedRowIds={selectedRowIds}
            />
            {pagination && pagination.total > pagination.pageSize && (
              <div className="adm-card__foot">
                <Pagination
                  onPageChange={pagination.onPageChange}
                  page={pagination.page}
                  pageSize={pagination.pageSize}
                  total={pagination.total}
                />
              </div>
            )}
          </>
        )}
      </Card>
    </>
  );
}
