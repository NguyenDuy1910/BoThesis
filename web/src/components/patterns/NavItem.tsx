"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

export type NavItemSize = "default" | "compact";

const SIZE: Record<NavItemSize, string> = {
  default: "h-10",
  compact: "h-9",
};

/**
 * One row in a rail, shared by all three modes.
 *
 * Selected carries three signals — a soft tint, an accent rule on the leading
 * edge, and an accent label — and two of the three survive a monochrome or
 * forced-colours rendering.
 */
export function NavItem({
  icon: Icon,
  label,
  href,
  onClick,
  active = false,
  size = "default",
  collapsed = false,
  trailing,
}: {
  icon: LucideIcon;
  label: string;
  /** Omit to render a button; an action row navigates nowhere. */
  href?: string;
  onClick?: () => void;
  active?: boolean;
  size?: NavItemSize;
  collapsed?: boolean;
  trailing?: React.ReactNode;
}) {
  const className = cn(
    "relative flex w-full min-w-0 items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5",
    "text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)]",
    "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
    "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-nav)]",
    SIZE[size],
    collapsed && "justify-center px-0",
    active
      ? "bg-[var(--surface-selected)] text-[var(--text-accent)]"
      : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
  );

  const body = (
    <>
      {active && (
        <span
          aria-hidden="true"
          className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-e-[2px] bg-[var(--accent-primary)]"
        />
      )}
      <Icon aria-hidden="true" className="shrink-0" size={20} />
      {!collapsed && <span className="min-w-0 flex-1 truncate text-left">{label}</span>}
      {!collapsed && trailing}
    </>
  );

  if (href) {
    return (
      <Link aria-current={active ? "page" : undefined} className={className} href={href} onClick={onClick} title={label}>
        {body}
      </Link>
    );
  }
  return (
    <button className={className} onClick={onClick} title={label} type="button">
      {body}
    </button>
  );
}
