"use client";

import { AlertTriangle, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface ErrorStateProps {
  title?: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  /** `block` fills the content area; `inline` sits inside a form or card. */
  layout?: "block" | "inline";
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description,
  actionLabel,
  onAction,
  layout = "block",
  className,
}: ErrorStateProps) {
  if (layout === "inline") {
    return (
      <div
        className={cn(
          "flex gap-2.5 rounded-[var(--radius-sm)] bg-[var(--status-danger-bg)] px-3 py-2.5",
          "text-[length:var(--text-size-ui)] text-[var(--status-danger-text)] shadow-[inset_0_0_0_1px_var(--status-danger-border)]",
          className,
        )}
        role="alert"
      >
        <AlertTriangle aria-hidden="true" className="mt-px h-4 w-4 shrink-0" />
        <p className="min-w-0 leading-5">{description}</p>
      </div>
    );
  }

  return (
    <div className={cn("ctl-card", className)} role="alert">
      <div className="ctl-empty">
        <span
          aria-hidden="true"
          className="ctl-empty__icon bg-[var(--status-danger-bg)] text-[var(--status-danger-solid)]"
        >
          <AlertTriangle className="h-5 w-5" />
        </span>
        <h3 className="ctl-empty__title">{title}</h3>
        <p className="ctl-empty__desc">{description}</p>
        {actionLabel && onAction && (
          <div className="ctl-empty__actions">
            <Button
              icon={<RotateCw aria-hidden="true" className="h-4 w-4" />}
              onClick={onAction}
              variant="ghost"
            >
              {actionLabel}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
