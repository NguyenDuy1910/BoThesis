"use client";

import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  /** Say what this surface will hold and what to do next — never "No data". */
  description?: string;
  /** The action that resolves the emptiness, plus at most one alternative. */
  action?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizePadding = {
  sm: "py-6",
  md: "py-10",
  lg: "",
} as const;

export function EmptyState({
  icon,
  title,
  description,
  action,
  size = "lg",
  className,
}: EmptyStateProps) {
  return (
    <div className={cn("ctl-empty", sizePadding[size], className)}>
      {icon && (
        <span aria-hidden="true" className="ctl-empty__icon">
          {icon}
        </span>
      )}
      <h3 className="ctl-empty__title text-balance">{title}</h3>
      {description && <p className="ctl-empty__desc text-pretty">{description}</p>}
      {action && <div className="ctl-empty__actions">{action}</div>}
    </div>
  );
}
