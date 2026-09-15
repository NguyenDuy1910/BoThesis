"use client";

import { cn } from "@/lib/cn";

/**
 * A binary setting that applies immediately.
 *
 * For a choice between two named policies use AccessOption instead: a toggle
 * cannot say what the other state means, and access decisions have to.
 */
export function Toggle({
  checked,
  onChange,
  disabled = false,
  label,
  describedBy,
}: {
  checked: boolean;
  onChange?: (next: boolean) => void;
  disabled?: boolean;
  /** Read out instead of the visual label, which lives in the row beside it. */
  label: string;
  describedBy?: string;
}) {
  return (
    <button
      aria-checked={checked}
      aria-describedby={describedBy}
      aria-label={label}
      className={cn(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1",
        "focus-visible:ring-offset-[var(--surface-base)]",
        checked
          ? "bg-[var(--action-primary-bg)] hover:bg-[var(--action-primary-hover)]"
          : "bg-[var(--status-neutral-border)] hover:bg-[var(--border-strong)]",
        disabled && "cursor-not-allowed opacity-55",
      )}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      role="switch"
      type="button"
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-0.5 h-[18px] w-[18px] rounded-full bg-[var(--surface-base)] shadow-sm",
          "transition-transform duration-[var(--duration-fast)] ease-[var(--ease-out)]",
          checked ? "translate-x-[18px]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}
