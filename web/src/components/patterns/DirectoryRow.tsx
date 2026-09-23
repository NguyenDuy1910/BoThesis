"use client";

import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/cn";
import { WorkspaceMark, type WorkspaceMarkTone } from "./WorkspaceMark";

/**
 * One workspace in Explore.
 *
 * Three lines of real information — what it is, what it knows, who provides it
 * and who may use it — rather than a marketing card. Scales to hundreds.
 */
export function DirectoryRow({
  title,
  description,
  provider,
  tone = "accent",
  onOpen,
  disabled = false,
  loading = false,
}: {
  title: string;
  description: string;
  provider: string;
  tone?: WorkspaceMarkTone;
  onOpen?: () => void;
  disabled?: boolean;
  loading?: boolean;
}) {
  return (
    <button
      className={cn(
        "group flex w-full min-w-0 items-center gap-3.5 rounded-[var(--radius-md)] px-3 py-3.5 text-left",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "hover:bg-[var(--surface-hover)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        "disabled:pointer-events-none disabled:opacity-60",
      )}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      onClick={onOpen}
      type="button"
    >
      <WorkspaceMark name={title} size="md" tone={tone} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[length:var(--text-size-body)] font-medium leading-[var(--text-lh-body)] text-[var(--text-primary)]">
          {title}
        </span>
        <span className="block truncate text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-secondary)]">
          {description}
        </span>
        <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
          {provider}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-1 text-[length:var(--text-size-nav)] font-medium text-[var(--text-secondary)] group-hover:text-[var(--text-accent)]">
        {loading ? "Opening…" : "Open"}
        <ChevronRight aria-hidden="true" size={18} />
      </span>
    </button>
  );
}
