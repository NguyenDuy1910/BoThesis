"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * A conversation in the rail.
 *
 * Selected uses a tint only — no accent rule, which is reserved for top-level
 * destinations so a rail never appears to have two current places. Renaming
 * happens in the row itself; a modal would lose the list you are renaming in.
 */
export function ConversationRow({
  title,
  active = false,
  renaming = false,
  onSelect,
  onRenameCommit,
  onRenameCancel,
  actions,
}: {
  title: string;
  active?: boolean;
  renaming?: boolean;
  onSelect?: () => void;
  onRenameCommit?: (next: string) => void;
  onRenameCancel?: () => void;
  /** Overflow menu, revealed on hover or keyboard focus. */
  actions?: React.ReactNode;
}) {
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!renaming) return;
    setDraft(title);
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [renaming, title]);

  if (renaming) {
    return (
      <div className="rounded-[var(--radius-sm)] px-1 py-0.5">
        <input
          className={cn(
            "w-full rounded-[var(--radius-sm)] bg-[var(--surface-base)] px-2 py-1.5",
            "text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-primary)]",
            "outline-none ring-2 ring-[var(--focus-ring)]",
          )}
          onBlur={() => onRenameCommit?.(draft.trim() || title)}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onRenameCommit?.(draft.trim() || title);
            if (event.key === "Escape") onRenameCancel?.();
          }}
          ref={inputRef}
          value={draft}
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex w-full min-w-0 items-center gap-1.5 rounded-[var(--radius-sm)]",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        active ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
      )}
    >
      <button
        className={cn(
          "min-w-0 flex-1 truncate py-2 pl-2.5 text-left",
          "text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
          "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-nav)] rounded-[var(--radius-sm)]",
          active ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]",
        )}
        onClick={onSelect}
        title={title}
        type="button"
      >
        {title}
      </button>
      {actions && (
        <span
          className={cn(
            "shrink-0 pr-1.5 opacity-0 transition-opacity",
            "group-hover:opacity-100 group-focus-within:opacity-100",
            active && "opacity-100",
          )}
        >
          {actions}
        </span>
      )}
    </div>
  );
}
