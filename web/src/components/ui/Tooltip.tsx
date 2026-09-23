"use client";

import { cn } from "@/lib/cn";

interface TooltipProps {
  label: string;
  children: React.ReactNode;
  /** Point it away from the nearest edge so it is never clipped. */
  side?: "top" | "bottom";
  className?: string;
}

const sideClasses = {
  top: "bottom-full mb-1.5",
  bottom: "top-full mt-1.5",
} as const;

/**
 * A tooltip names an unlabelled control. It never carries information the
 * screen does not already provide, because touch users never see it.
 */
export function Tooltip({ label, children, side = "bottom", className }: TooltipProps) {
  return (
    <span className={cn("group/tooltip relative inline-flex", className)}>
      {children}
      <span
        className={cn(
          "pointer-events-none invisible absolute left-1/2 z-[70] -translate-x-1/2 whitespace-nowrap opacity-0",
          "rounded-[var(--radius-xs)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] px-1.5 py-1 text-[length:var(--text-size-caption)] font-medium text-[var(--text-secondary)]",
          "shadow-[var(--elevation-2)] transition-[opacity,visibility] duration-[var(--duration-fast)] ease-[var(--ease-out)]",
          "group-focus-within/tooltip:visible group-focus-within/tooltip:opacity-100 group-hover/tooltip:visible group-hover/tooltip:opacity-100",
          sideClasses[side],
        )}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
