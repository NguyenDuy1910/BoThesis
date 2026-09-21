"use client";

import { cn } from "@/lib/cn";

export type BadgeTone =
  | "neutral"
  | "brand"
  | "success"
  | "warning"
  | "danger"
  | "info";

/** Legacy aliases kept so older call sites keep compiling. */
type BadgeVariant = BadgeTone | "default" | "primary";

const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-[var(--status-neutral-bg)] text-[var(--status-neutral-text)]",
  brand: "bg-[var(--accent-soft)] text-[var(--text-accent)]",
  success: "bg-[var(--status-success-bg)] text-[var(--status-success-text)]",
  warning: "bg-[var(--status-warning-bg)] text-[var(--status-warning-text)]",
  danger: "bg-[var(--status-danger-bg)] text-[var(--status-danger-text)]",
  info: "bg-[var(--status-info-bg)] text-[var(--status-info-text)]",
};

const dotClasses: Record<BadgeTone, string> = {
  neutral: "bg-[var(--status-neutral-solid)]",
  brand: "bg-[var(--text-accent)]",
  success: "bg-[var(--status-success-solid)]",
  warning: "bg-[var(--status-warning-solid)]",
  danger: "bg-[var(--status-danger-solid)]",
  info: "bg-[var(--status-info-solid)]",
};

function normalizeTone(value: BadgeVariant): BadgeTone {
  if (value === "default") return "neutral";
  if (value === "primary") return "brand";
  return value;
}

interface BadgeProps {
  tone?: BadgeTone;
  /** @deprecated use `tone` */
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
  /** Adds a slow pulse to the dot for states that are still moving. */
  pulse?: boolean;
  icon?: React.ReactNode;
}

export function Badge({
  tone,
  variant,
  children,
  className,
  dot = false,
  pulse = false,
  icon,
}: BadgeProps) {
  const resolved = normalizeTone(tone ?? variant ?? "neutral");
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-[var(--radius-xs)] px-1.5 py-0.5",
        "text-[length:var(--text-size-meta)] font-medium leading-4",
        toneClasses[resolved],
        className,
      )}
    >
      {dot && (
        <span
          aria-hidden="true"
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            dotClasses[resolved],
            pulse && "motion-safe:animate-pulse",
          )}
        />
      )}
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}
