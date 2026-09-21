"use client";

import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("ctl-skeleton", className)} />;
}

export function SkeletonLine({ className }: { className?: string }) {
  return <Skeleton className={cn("h-3 w-full", className)} />;
}

/**
 * Loading placeholders mirror the shape of what is coming so the layout does
 * not jump when data lands.
 */
export function TableSkeleton({
  rows = 6,
  columns = 4,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <div aria-busy="true" aria-live="polite" className="divide-y divide-[var(--border-subtle)]">
      <span className="sr-only">Loading</span>
      <div className="flex items-center gap-4 bg-[var(--surface-inset)] px-3.5 py-2.5">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton className="h-2.5 flex-1" key={index} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div className="flex items-center gap-4 px-3.5 py-3" key={rowIndex}>
          {Array.from({ length: columns }).map((_, columnIndex) => (
            <Skeleton
              className={cn("h-3", columnIndex === 0 ? "flex-[2]" : "flex-1")}
              key={columnIndex}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function StatsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div aria-busy="true" className="ctl-stats">
      {Array.from({ length: count }).map((_, index) => (
        <div className="ctl-stat" key={index}>
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-16" />
          <Skeleton className="h-2.5 w-20" />
        </div>
      ))}
    </div>
  );
}

export function CardListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div aria-busy="true" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <div className="ctl-card p-4" key={index}>
          <div className="flex items-center gap-3">
            <Skeleton className="h-9 w-9 rounded-[var(--radius-md)]" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-2.5 w-1/3" />
            </div>
          </div>
          <Skeleton className="mt-4 h-2.5 w-full" />
          <Skeleton className="mt-2 h-2.5 w-4/5" />
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div aria-busy="true" className="space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-3 w-96" />
      </div>
      <div className="ctl-stats">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton className="h-20" key={index} />
        ))}
      </div>
      <div className="ctl-card">
        <TableSkeleton rows={5} />
      </div>
    </div>
  );
}
