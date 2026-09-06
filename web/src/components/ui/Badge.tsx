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
  neutral: "bg-[var(--neutral-soft)] text-[var(--neutral-text)]",
  brand: "bg-[var(--brand-accent-soft)] text-[var(--brand-accent)]",
  success: "bg-[var(--success-soft)] text-[var(--success-text)]",
  warning: "bg-[var(--warning-soft)] text-[var(--warning-text)]",
  danger: "bg-[var(--danger-soft)] text-[var(--danger-text)]",
  info: "bg-[var(--info-soft)] text-[var(--info-text)]",
};

const dotClasses: Record<BadgeTone, string> = {
  neutral: "bg-[var(--neutral)]",
  brand: "bg-[var(--brand-accent)]",
  success: "bg-[var(--success)]",
  warning: "bg-[var(--warning)]",
  danger: "bg-[var(--danger)]",
  info: "bg-[var(--info)]",
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
        "inline-flex max-w-full items-center gap-1.5 rounded-[var(--adm-r-xs)] px-1.5 py-0.5",
        "text-[0.75rem] font-medium leading-4",
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
