"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { cn } from "@/lib/cn";

/** States the current rail context, with an optional return link for admin modes. */
export function ContextHeader({
  name,
  context,
  backHref,
  onNavigate,
  collapsed = false,
}: {
  name: string;
  context: string;
  /** Admin contexts link back to the workspace; the workspace header is informational. */
  backHref?: string;
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  if (collapsed) {
    if (!backHref) return null;
    return (
      <Link
        className={cn(
          "mx-auto flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)]",
          "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        )}
        href={backHref}
        onClick={onNavigate}
        title={`Back to ${name}`}
      >
        <ArrowLeft aria-hidden="true" size={18} />
      </Link>
    );
  }

  const className = cn(
    "flex h-[52px] w-full flex-col gap-px rounded-[var(--radius-sm)] px-2 pb-2 pt-[7px]",
    backHref && "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)] hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
  );
  const content = (
    <>
      <span className="min-w-0 truncate text-left text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
        {name}
      </span>
      <span className="text-[length:var(--text-size-caption)] font-medium uppercase leading-[var(--text-lh-caption)] tracking-[var(--text-tracking-caption)] text-[var(--text-accent)]">
        {context}
      </span>
    </>
  );

  if (!backHref) return <div className={className}>{content}</div>;

  return (
    <Link className={className} href={backHref} onClick={onNavigate} title={`Back to ${name}`}>
      {content}
    </Link>
  );
}
