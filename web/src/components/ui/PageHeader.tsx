"use client";

import { cn } from "@/lib/cn";

interface PageHeaderProps {
  title: string;
  /** Small label above the title — the section this page belongs to. */
  eyebrow?: React.ReactNode;
  description?: string;
  /** Facts about the record, shown beside the title. */
  metadata?: React.ReactNode;
  /** Exactly one primary action; everything else secondary or in a menu. */
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  title,
  eyebrow,
  description,
  metadata,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("ctl-head", className)}>
      <div className="ctl-head__text">
        {eyebrow && <p className="ctl-head__eyebrow">{eyebrow}</p>}
        <h1 className="ctl-head__title">
          <span className="min-w-0 text-balance">{title}</span>
          {metadata && (
            <span className="flex min-w-0 flex-wrap items-center gap-2 text-[length:var(--text-size-ui)] font-normal text-[var(--text-tertiary)]">
              {metadata}
            </span>
          )}
        </h1>
        {description && <p className="ctl-head__desc">{description}</p>}
      </div>
      {actions && <div className="ctl-head__actions">{actions}</div>}
    </header>
  );
}
