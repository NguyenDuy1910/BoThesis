"use client";

import { cn } from "@/lib/cn";

/**
 * A workspace-authored opening question, configured in Experience.
 *
 * Three or four maximum — a wall of chips is a menu, not a conversation.
 */
export function StarterPrompt({ label, onSelect }: { label: string; onSelect?: () => void }) {
  return (
    <button
      className={cn(
        "rounded-[var(--radius-md)] bg-[var(--surface-base)] px-3.5 py-2.5",
        "text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-primary)]",
        "ring-1 ring-inset ring-[var(--border-subtle)]",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "hover:bg-[var(--surface-hover)] hover:ring-[var(--border-default)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
      )}
      onClick={onSelect}
      type="button"
    >
      {label}
    </button>
  );
}
