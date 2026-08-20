"use client";

import { cn } from "@/lib/cn";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn("animate-pulse rounded-xl bg-slate-200/80", className)}
    />
  );
}

export function SkeletonLine({ className }: SkeletonProps) {
  return <Skeleton className={cn("h-3 w-full", className)} />;
}

export function TreeSkeleton() {
  return (
    <div className="space-y-2 p-3">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2 ml-4" />
      <Skeleton className="h-4 w-2/3 ml-4" />
      <Skeleton className="h-4 w-3/5 ml-8" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-2/3 ml-4" />
      <Skeleton className="h-4 w-1/3 ml-4" />
    </div>
  );
}

export function ListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-2 px-4 py-3">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="p-4 space-y-4">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-3 w-full" />
      <div className="grid grid-cols-2 gap-3 mt-4">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
      <Skeleton className="h-4 w-1/3 mt-6" />
      <Skeleton className="h-20" />
      <Skeleton className="h-20" />
    </div>
  );
}
