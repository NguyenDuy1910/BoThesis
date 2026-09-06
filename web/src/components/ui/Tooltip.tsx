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
          "pointer-events-none absolute left-1/2 z-[70] hidden -translate-x-1/2 whitespace-nowrap",
          "rounded-[var(--adm-r-xs)] bg-[var(--text)] px-1.5 py-1 text-[0.6875rem] font-medium text-[var(--adm-surface)]",
          "shadow-[var(--adm-e2)] group-focus-within/tooltip:block group-hover/tooltip:block",
          sideClasses[side],
        )}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
