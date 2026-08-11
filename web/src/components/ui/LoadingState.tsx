"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

interface LoadingStateProps {
  title?: string;
  description?: string;
  className?: string;
}

export function LoadingState({
  title = "Loading",
  description,
  className,
}: LoadingStateProps) {
  return (
    <div
      className={cn(
        "flex min-h-40 flex-col items-center justify-center border-y border-slate-200 bg-white px-4 py-8 text-center",
        className
      )}
      aria-live="polite"
      aria-busy="true"
    >
      <span className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded-md bg-teal-50 text-teal-700 ring-1 ring-inset ring-teal-100">
        <Loader2 className="h-4 w-4 animate-spin" />
      </span>
      <p className="text-sm font-semibold text-slate-950">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm leading-5 text-slate-600">{description}</p>}
    </div>
  );
}
