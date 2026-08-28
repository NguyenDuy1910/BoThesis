"use client";

import { cn } from "@/lib/cn";

interface TooltipProps {
  label: string;
  children: React.ReactNode;
  className?: string;
}

export function Tooltip({ label, children, className }: TooltipProps) {
  return (
    <span className={cn("group/tooltip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden max-w-64 -translate-x-1/2 whitespace-nowrap rounded-md border border-[var(--border-strong)] bg-[var(--text)] px-2 py-1 text-xs font-medium text-[var(--surface)] shadow-[var(--shadow-popover)] group-hover/tooltip:block group-focus-within/tooltip:block"
      >
        {label}
      </span>
    </span>
  );
}
