import { cn } from "@/lib/cn";

export type StatusTone = "neutral" | "success" | "info" | "warning" | "danger" | "accent";

const TONE: Record<StatusTone, { shell: string; dot: string }> = {
  neutral: {
    shell: "bg-[var(--status-neutral-bg)] text-[var(--status-neutral-text)] ring-[var(--status-neutral-border)]",
    dot: "bg-[var(--status-neutral-solid)]",
  },
  success: {
    shell: "bg-[var(--status-success-bg)] text-[var(--status-success-text)] ring-[var(--status-success-border)]",
    dot: "bg-[var(--status-success-solid)]",
  },
  info: {
    shell: "bg-[var(--status-info-bg)] text-[var(--status-info-text)] ring-[var(--status-info-border)]",
    dot: "bg-[var(--status-info-solid)]",
  },
  warning: {
    shell: "bg-[var(--status-warning-bg)] text-[var(--status-warning-text)] ring-[var(--status-warning-border)]",
    dot: "bg-[var(--status-warning-solid)]",
  },
  danger: {
    shell: "bg-[var(--status-danger-bg)] text-[var(--status-danger-text)] ring-[var(--status-danger-border)]",
    dot: "bg-[var(--status-danger-solid)]",
  },
  accent: {
    shell: "bg-[var(--accent-soft)] text-[var(--text-accent)] ring-[var(--status-neutral-border)]",
    dot: "bg-[var(--accent-primary)]",
  },
};

/**
 * State, not decoration. At most one per row.
 *
 * Access state uses `neutral` for members-only and `info` for everyone, so the
 * two are told apart by hue as well as by wording.
 */
export function StatusPill({
  tone = "neutral",
  children,
  className,
}: {
  tone?: StatusTone;
  children: React.ReactNode;
  className?: string;
}) {
  const { shell, dot } = TONE[tone];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-full)] py-[3px] pl-2 pr-2.5",
        "text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] ring-1 ring-inset",
        shell,
        className,
      )}
    >
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", dot)} />
      {children}
    </span>
  );
}
