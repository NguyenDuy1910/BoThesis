"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/cn";
import { WorkspaceMark, type WorkspaceMarkTone } from "./WorkspaceMark";

/**
 * One workspace in the switcher or the directory.
 *
 * Name plus one line of orienting detail — the providing organisation. No
 * badges: membership versus public access is carried by the section heading,
 * not by a chip on every row.
 */
export function WorkspaceRow({
  name,
  sublabel,
  tone = "accent",
  current = false,
  onSelect,
  actions,
}: {
  name: string;
  sublabel: string;
  tone?: WorkspaceMarkTone;
  current?: boolean;
  onSelect?: () => void;
  /** Open / Manage workspace, revealed on hover for people with the scope. */
  actions?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "group relative flex w-full min-w-0 items-center gap-2.5 rounded-[var(--radius-sm)]",
        current ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
    >
      <button
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-2 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        )}
        onClick={onSelect}
        type="button"
      >
        <WorkspaceMark name={name} size="md" tone={tone} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
            {name}
          </span>
          <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {sublabel}
          </span>
        </span>
        {current && <Check aria-hidden="true" className="shrink-0 text-[var(--text-accent)]" size={18} />}
      </button>
      {actions && (
        <span className="shrink-0 pr-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {actions}
        </span>
      )}
    </div>
  );
}
