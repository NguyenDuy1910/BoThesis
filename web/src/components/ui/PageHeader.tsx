"use client";

import { cn } from "@/lib/cn";

interface PageHeaderProps {
  title: string;
  description?: string;
  metadata?: React.ReactNode;
  actions?: React.ReactNode;
  sticky?: boolean;
  className?: string;
}

export function PageHeader({ title, description, metadata, actions, sticky = false, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        "mb-4 flex min-h-14 flex-col gap-2 border-b border-[var(--border)] pb-3 sm:flex-row sm:items-center sm:justify-between",
        sticky && "sticky top-12 z-10 bg-[var(--bg-panel)] pt-1 backdrop-blur",
        className
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="min-w-0 text-balance text-2xl font-semibold leading-8 text-[var(--text)]">{title}</h1>
          {metadata && (
            <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
              {metadata}
            </div>
          )}
        </div>
        {description && <p className="mt-0.5 max-w-3xl text-pretty text-sm leading-5 text-[var(--text-muted)]">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{actions}</div>}
    </div>
  );
}
