"use client";

import { cn } from "@/lib/cn";

type EmptyStateSize = "sm" | "md" | "lg";

const sizeClasses: Record<EmptyStateSize, { wrapper: string; icon: string; title: string }> = {
  sm: { wrapper: "py-6", icon: "mb-2", title: "text-sm" },
  md: { wrapper: "py-8", icon: "mb-2", title: "text-sm" },
  lg: { wrapper: "py-10", icon: "mb-3", title: "text-base" },
};

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  size?: EmptyStateSize;
  className?: string;
}

export function EmptyState({ icon, title, description, action, size = "lg", className }: EmptyStateProps) {
  const s = sizeClasses[size];
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", s.wrapper, className)}>
      {icon && <div aria-hidden="true" className={cn("rounded-md bg-[var(--primary-soft)] p-2.5 text-[var(--brand-accent)] ring-1 ring-inset ring-[var(--border)]", s.icon)}>{icon}</div>}
      <h3 className={cn("font-semibold text-[var(--text)] text-balance", s.title)}>{title}</h3>
      {description && <p className="mt-1 max-w-sm text-pretty text-sm leading-5 text-[var(--text-muted)]">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
