"use client";

import { X, type LucideIcon } from "lucide-react";
import { Paperclip } from "lucide-react";

import { cn } from "@/lib/cn";

export type AttachmentState = "ready" | "uploading" | "error";

/**
 * One attachment in the composer.
 *
 * Progress is a 2px rule along the bottom edge, not a spinner or a percentage
 * ring. An unsupported file fails at attach time — before the message is sent —
 * so it can be fixed while still composing.
 */
export function AttachmentChip({
  name,
  meta,
  state = "ready",
  progress = 0,
  icon: Icon = Paperclip,
  onRemove,
}: {
  name: string;
  meta: string;
  state?: AttachmentState;
  /** 0–1, only read while uploading. */
  progress?: number;
  icon?: LucideIcon;
  onRemove?: () => void;
}) {
  const error = state === "error";
  return (
    <span
      className={cn(
        "relative flex w-[248px] min-w-0 items-center gap-2.5 overflow-hidden rounded-[var(--radius-sm)] py-[7px] pl-2.5 pr-2",
        "ring-1 ring-inset",
        error
          ? "bg-[var(--status-danger-bg)] ring-[var(--status-danger-border)]"
          : "bg-[var(--surface-base)] ring-[var(--border-subtle)]",
      )}
    >
      <Icon aria-hidden="true" className="shrink-0 text-[var(--text-tertiary)]" size={20} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
          {name}
        </span>
        <span
          className={cn(
            "block truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)]",
            error ? "text-[var(--status-danger-text)]" : "text-[var(--text-tertiary)]",
          )}
        >
          {meta}
        </span>
      </span>
      <button
        aria-label={`Remove ${name}`}
        className="shrink-0 rounded-[var(--radius-xs)] p-0.5 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        onClick={onRemove}
        type="button"
      >
        <X aria-hidden="true" size={16} />
      </button>
      {state === "uploading" && (
        <span
          aria-hidden="true"
          className="absolute bottom-0 left-0 h-0.5 bg-[var(--accent-primary)] transition-[width]"
          style={{ width: `${Math.round(Math.min(Math.max(progress, 0), 1) * 100)}%` }}
        />
      )}
    </span>
  );
}
