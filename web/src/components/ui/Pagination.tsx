"use client";

import { cn } from "@/lib/cn";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}

export function Pagination({ page, pageSize, total, onPageChange, className }: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className={cn("flex min-h-11 flex-col gap-2 border-b border-slate-200 bg-white px-3 py-2 sm:flex-row sm:items-center sm:justify-between", className)}>
      <p className="text-xs text-slate-600">
        Showing {start}-{end} of {total}
      </p>
      <div className="flex items-center gap-1">
        <button
          aria-label="Previous page"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-600 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20 disabled:pointer-events-none disabled:text-slate-300"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
          let pageNum: number;
          if (totalPages <= 5) {
            pageNum = i + 1;
          } else if (page <= 3) {
            pageNum = i + 1;
          } else if (page >= totalPages - 2) {
            pageNum = totalPages - 4 + i;
          } else {
            pageNum = page - 2 + i;
          }
          return (
            <button
              key={pageNum}
              aria-current={page === pageNum ? "page" : undefined}
              onClick={() => onPageChange(pageNum)}
              className={cn(
                "inline-flex h-7 w-7 items-center justify-center rounded-md text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20",
                page === pageNum
                  ? "bg-teal-700 text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
              )}
            >
              {pageNum}
            </button>
          );
        })}
        <button
          aria-label="Next page"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-600 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20 disabled:pointer-events-none disabled:text-slate-300"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
