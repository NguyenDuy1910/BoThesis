"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/** Page numbers around the current page, with the ends always reachable. */
function pageWindow(page: number, totalPages: number): (number | "gap")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  const pages = new Set<number>([1, totalPages, page, page - 1, page + 1]);
  const sorted = [...pages].filter((value) => value >= 1 && value <= totalPages).sort((a, b) => a - b);
  const result: (number | "gap")[] = [];
  sorted.forEach((value, index) => {
    if (index > 0 && value - (sorted[index - 1] as number) > 1) result.push("gap");
    result.push(value);
  });
  return result;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
}: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <nav
      aria-label="Pagination"
      className={cn(
        "flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <p className="text-[length:var(--text-size-meta)] tabular-nums text-[var(--text-tertiary)]">
        {start.toLocaleString()}–{end.toLocaleString()} of {total.toLocaleString()}
      </p>
      <div className="flex items-center gap-0.5">
        <button
          aria-label="Previous page"
          className={cn(ui.iconButton, "h-7 w-7")}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          type="button"
        >
          <ChevronLeft aria-hidden="true" className="h-4 w-4" />
        </button>
        {pageWindow(page, totalPages).map((entry, index) =>
          entry === "gap" ? (
            <span
              aria-hidden="true"
              className="px-1 text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]"
              key={`gap-${index}`}
            >
              …
            </span>
          ) : (
            <button
              aria-current={page === entry ? "page" : undefined}
              aria-label={`Page ${entry}`}
              className={cn(
                "inline-flex h-7 min-w-7 items-center justify-center rounded-[var(--radius-xs)] px-1.5 text-[length:var(--text-size-meta)] font-medium tabular-nums transition-colors",
                ui.focus,
                page === entry
                  ? "bg-[var(--accent-primary)] text-[var(--text-on-accent)]"
                  : "text-[var(--text-tertiary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
              )}
              key={entry}
              onClick={() => onPageChange(entry)}
              type="button"
            >
              {entry}
            </button>
          ),
        )}
        <button
          aria-label="Next page"
          className={cn(ui.iconButton, "h-7 w-7")}
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          type="button"
        >
          <ChevronRight aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    </nav>
  );
}
