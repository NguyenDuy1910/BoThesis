"use client";

import { cn } from "@/lib/cn";

type BadgeVariant = "default" | "primary" | "success" | "warning" | "danger" | "info";

const variantClasses: Record<BadgeVariant, string> = {
  default: "bg-[var(--bg-subtle)] text-[var(--text-secondary)] ring-[var(--border)]",
  primary: "bg-[var(--primary-soft)] text-[var(--brand-accent)] ring-[var(--border)]",
  success: "bg-[var(--success-soft)] text-[var(--success)] ring-[var(--success-border)]",
  warning: "bg-[var(--warning-soft)] text-[var(--warning-text)] ring-[var(--warning-border)]",
  danger: "bg-[var(--danger-soft)] text-[var(--danger-text)] ring-[var(--danger-border)]",
  info: "bg-[var(--info-soft)] text-[var(--info-text)] ring-[var(--info-border)]",
};

const dotClasses: Record<BadgeVariant, string> = {
  default: "bg-[var(--text-muted)]",
  primary: "bg-[var(--brand-accent)]",
  success: "bg-[var(--success)]",
  warning: "bg-[var(--warning)]",
  danger: "bg-[var(--danger)]",
  info: "bg-[var(--info)]",
};

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}

export function Badge({ variant = "default", children, className, dot = false }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium leading-5 ring-1 ring-inset",
        variantClasses[variant],
        className
      )}
    >
      {dot && <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", dotClasses[variant])} />}
      {children}
    </span>
  );
}
