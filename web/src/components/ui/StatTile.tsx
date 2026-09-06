"use client";

import Link from "next/link";

import { cn } from "@/lib/cn";

interface StatTileProps {
  label: string;
  /** `undefined` renders an em dash — the value is unavailable, not zero. */
  value: number | string | undefined;
  icon?: React.ReactNode;
  /** Short qualifier under the number, e.g. "3 need attention". */
  note?: React.ReactNode;
  /** Makes the whole tile a link to the page that explains the number. */
  href?: string;
  tone?: "default" | "warning" | "danger";
  className?: string;
}

const toneClasses = {
  default: "",
  warning: "text-[var(--warning-text)]",
  danger: "text-[var(--danger-text)]",
} as const;

export function StatTile({
  label,
  value,
  icon,
  note,
  href,
  tone = "default",
  className,
}: StatTileProps) {
  const body = (
    <>
      <span className="adm-stat__top">
        {icon}
        {label}
      </span>
      <span className={cn("adm-stat__value", toneClasses[tone])}>
        {value === undefined ? (
          <span aria-label="Not available">—</span>
        ) : typeof value === "number" ? (
          value.toLocaleString()
        ) : (
          value
        )}
      </span>
      {note && <span className="adm-stat__note">{note}</span>}
    </>
  );

  if (href) {
    return (
      <Link
        className={cn(
          "adm-stat focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--adm-canvas)]",
          className,
        )}
        href={href}
      >
        {body}
      </Link>
    );
  }

  return <div className={cn("adm-stat", className)}>{body}</div>;
}

export function StatGrid({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("adm-stats", className)}>{children}</div>;
}
