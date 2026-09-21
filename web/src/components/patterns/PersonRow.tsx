"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * One person, in workspace Members or Platform Users.
 *
 * The select checkbox appears on hover or once a selection is active, so a
 * resting table is not covered in controls. Pending invitations are dimmed and
 * carry no last-active value.
 */
export function PersonRow({
  name,
  email,
  role,
  groups,
  lastActive,
  selected = false,
  pending = false,
  selectable = true,
  onToggleSelect,
  onOpen,
  actions,
}: {
  name: string;
  email: string;
  role: string;
  groups: string;
  lastActive: string;
  selected?: boolean;
  pending?: boolean;
  selectable?: boolean;
  onToggleSelect?: () => void;
  onOpen?: () => void;
  actions?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "group flex w-full min-w-0 items-center gap-4 rounded-[var(--radius-sm)] px-3",
        selected ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--surface-hover)]",
        pending && "opacity-60",
      )}
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
        {selectable && (
          <button
            aria-checked={selected}
            aria-label={`Select ${name}`}
            className={cn(
              "flex h-4 w-4 items-center justify-center rounded-[var(--radius-xs)] transition-opacity",
              selected
                ? "bg-[var(--accent-primary)] opacity-100"
                : "bg-[var(--surface-base)] opacity-0 ring-1 ring-inset ring-[var(--border-default)] group-hover:opacity-100 group-focus-within:opacity-100",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
            )}
            onClick={onToggleSelect}
            role="checkbox"
            type="button"
          >
            {selected && <Check aria-hidden="true" className="text-[var(--text-on-accent)]" size={12} />}
          </button>
        )}
      </span>
      <button
        className={cn(
          "flex min-w-0 flex-1 items-center gap-4 rounded-[var(--radius-sm)] py-2.5 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        )}
        onClick={onOpen}
        type="button"
      >
        <span aria-hidden="true" className="h-8 w-8 shrink-0 rounded-full bg-[var(--status-neutral-solid)]" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
            {name}
          </span>
          <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {email}
          </span>
        </span>
        <span className="hidden w-[150px] shrink-0 truncate text-[length:var(--text-size-nav)] text-[var(--text-secondary)] md:block">
          {role}
        </span>
        <span className="hidden w-[170px] shrink-0 truncate text-[length:var(--text-size-nav)] text-[var(--text-secondary)] lg:block">
          {groups}
        </span>
        <span className="hidden w-[130px] shrink-0 truncate text-[length:var(--text-size-meta)] text-[var(--text-tertiary)] lg:block">
          {lastActive}
        </span>
      </button>
      <span className="w-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {actions}
      </span>
    </div>
  );
}
