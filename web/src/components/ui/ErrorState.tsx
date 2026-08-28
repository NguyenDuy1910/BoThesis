"use client";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { AlertCircle } from "lucide-react";

interface ErrorStateProps {
  title?: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description,
  actionLabel,
  onAction,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        "rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-3 text-sm text-[var(--danger-text)]",
        className
      )}
      role="alert"
    >
      <div className="flex gap-3">
        <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--danger)]" />
        <div className="min-w-0 space-y-1">
          <p className="font-semibold">{title}</p>
          <p className="leading-5 text-[var(--danger-text)]">{description}</p>
          {actionLabel && onAction && (
            <Button className="mt-2" onClick={onAction} size="sm" variant="danger">
              {actionLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
