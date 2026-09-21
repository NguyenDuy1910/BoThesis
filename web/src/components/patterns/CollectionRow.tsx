"use client";

import { BookOpen, ChevronRight, Lock, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * A grouping of documents, listed inline above the documents themselves.
 *
 * This is what replaces a second sidebar: hierarchy is walked through rows and
 * a breadcrumb, so no horizontal space is permanently spent on navigation.
 * A restricted collection keeps its count so totals reconcile, but never opens.
 */
export function CollectionRow({
  name,
  source,
  count,
  icon: Icon = BookOpen,
  restricted = false,
  onOpen,
}: {
  name: string;
  source: string;
  count: number;
  icon?: LucideIcon;
  restricted?: boolean;
  onOpen?: () => void;
}) {
  const Mark = restricted ? Lock : Icon;
  const body = (
    <>
      {/* The mark sits in the same 28px column a document's file mark occupies,
          so a collection row and the document rows under it start their names
          on one edge. */}
      <span aria-hidden="true" className="grid h-7 w-7 shrink-0 place-items-center text-[var(--text-tertiary)]">
        <Mark size={20} />
      </span>
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)]",
            restricted ? "text-[var(--text-secondary)]" : "text-[var(--text-primary)]",
          )}
        >
          {name}
        </span>
        <span className="block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
          {source}
        </span>
      </span>
      <span className="w-[86px] shrink-0 text-right text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-tertiary)]">
        {count.toLocaleString()}
      </span>
      {restricted ? (
        <span className="shrink-0 text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">Restricted</span>
      ) : (
        <ChevronRight aria-hidden="true" className="shrink-0 text-[var(--text-tertiary)]" size={18} />
      )}
    </>
  );

  if (restricted) {
    return (
      <div
        className="flex w-full min-w-0 items-center gap-3 rounded-[var(--radius-sm)] px-3 py-3"
        title="You can see that this collection exists because its documents count toward the workspace total, but you cannot open it."
      >
        {body}
      </div>
    );
  }

  return (
    <button
      className={cn(
        "flex w-full min-w-0 items-center gap-3 rounded-[var(--radius-sm)] px-3 py-3 text-left",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "hover:bg-[var(--surface-hover)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
      )}
      onClick={onOpen}
      type="button"
    >
      {body}
    </button>
  );
}
