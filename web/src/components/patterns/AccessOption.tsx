"use client";

import { cn } from "@/lib/cn";

/**
 * A mutually exclusive policy choice, stated in product language.
 *
 * Disabled means the current admin lacks the scope to pick it — it is paired
 * with a reason and never hidden, so the full policy stays legible.
 */
export function AccessOption({
  title,
  description,
  selected = false,
  disabled = false,
  name,
  onSelect,
}: {
  title: string;
  description: string;
  selected?: boolean;
  disabled?: boolean;
  /** Radio group name; every option of one decision shares it. */
  name: string;
  onSelect?: () => void;
}) {
  return (
    <label
      className={cn(
        "flex w-full cursor-pointer items-start gap-3 rounded-[var(--radius-md)] px-3.5 pb-3.5 pt-3",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        selected
          ? "bg-[var(--surface-base)] ring-[1.5px] ring-inset ring-[var(--accent-primary)]"
          : "ring-1 ring-inset ring-[var(--border-subtle)]",
        disabled && "cursor-not-allowed opacity-55",
      )}
    >
      <input
        checked={selected}
        className="sr-only"
        disabled={disabled}
        name={name}
        onChange={() => onSelect?.()}
        type="radio"
      />
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full",
          selected
            ? "border-[5px] border-[var(--accent-primary)]"
            : "border-[1.25px] border-[var(--border-default)]",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="block text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
          {title}
        </span>
        <span className="mt-0.5 block text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-secondary)]">
          {description}
        </span>
      </span>
    </label>
  );
}
