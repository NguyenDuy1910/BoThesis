"use client";

import { Copy, Download, RotateCcw, ThumbsDown, ThumbsUp, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * Copy, retry, rate, export.
 *
 * Revealed on hover or focus of the assistant turn and always present for the
 * last turn, so the primary path never depends on hover. Rating writes to the
 * workspace quality log, not into the conversation.
 */
export function MessageActions({
  onCopy,
  onRetry,
  onGood,
  onBad,
  onExport,
  className,
}: {
  onCopy?: () => void;
  onRetry?: () => void;
  onGood?: () => void;
  onBad?: () => void;
  onExport?: () => void;
  className?: string;
}) {
  const actions: { id: string; icon: LucideIcon; label: string; run?: () => void }[] = [
    { id: "copy", icon: Copy, label: "Copy answer", run: onCopy },
    { id: "retry", icon: RotateCcw, label: "Retry", run: onRetry },
    { id: "good", icon: ThumbsUp, label: "Good answer", run: onGood },
    { id: "bad", icon: ThumbsDown, label: "Poor answer", run: onBad },
    { id: "export", icon: Download, label: "Export", run: onExport },
  ];
  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {actions
        .filter((action) => action.run)
        .map(({ id, icon: Icon, label, run }) => (
          <button
            aria-label={label}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)]",
              "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
              "hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
            )}
            key={id}
            onClick={run}
            title={label}
            type="button"
          >
            <Icon aria-hidden="true" size={18} />
          </button>
        ))}
    </div>
  );
}
