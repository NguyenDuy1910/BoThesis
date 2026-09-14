"use client";

import { ArrowUp, ChevronDown, Lock, Plus, X } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * A capability chip: the live context a question will be answered with.
 *
 * Stating knowledge scope, web access and model in the composer lets a person
 * see what will answer before they ask, rather than after.
 */
export function CapabilityChip({
  label,
  onClick,
  muted = false,
}: {
  label: string;
  onClick?: () => void;
  muted?: boolean;
}) {
  return (
    <button
      className={cn(
        "flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-[5px]",
        "bg-[var(--surface-base)] ring-1 ring-inset ring-[var(--border-subtle)]",
        "text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)]",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        muted ? "text-[var(--text-tertiary)]" : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]",
      )}
      disabled={muted}
      onClick={onClick}
      type="button"
    >
      {label}
      <ChevronDown aria-hidden="true" className="text-[var(--text-tertiary)]" size={14} />
    </button>
  );
}

/**
 * The production composer.
 *
 * Send is inert until there is content; while generating it becomes Stop, so
 * the action is never ambiguous. Attachments validate at attach time. The
 * input grows to eight lines and then scrolls internally rather than pushing
 * the conversation off screen.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  onAttach,
  generating = false,
  disabled = false,
  dragOver = false,
  placeholder = "Ask BoThesis…",
  attachments,
  capabilities,
  error,
  disabledReason,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit?: () => void;
  onStop?: () => void;
  onAttach?: () => void;
  generating?: boolean;
  disabled?: boolean;
  dragOver?: boolean;
  placeholder?: string;
  attachments?: React.ReactNode;
  capabilities?: React.ReactNode;
  /** Why the last send failed, with its retry. */
  error?: React.ReactNode;
  /** Why this person cannot send at all. */
  disabledReason?: React.ReactNode;
}) {
  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div
      className={cn(
        "flex w-full flex-col gap-3 rounded-[var(--radius-2xl)] px-4 pb-3 pt-3.5",
        "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        dragOver
          ? "bg-[var(--accent-soft)] ring-2 ring-inset ring-[var(--accent-primary)] [border-style:dashed]"
          : disabled
            ? "bg-[var(--surface-subtle)] ring-1 ring-inset ring-[var(--border-subtle)]"
            : error
              ? "bg-[var(--surface-base)] ring-1 ring-inset ring-[var(--status-danger-border)]"
              : "bg-[var(--surface-base)] ring-1 ring-inset ring-[var(--border-default)] focus-within:ring-2 focus-within:ring-[var(--focus-ring)]",
      )}
    >
      {attachments && <div className="flex flex-wrap gap-2">{attachments}</div>}

      {dragOver ? (
        <p className="py-1 text-[length:var(--text-size-body)] leading-[var(--text-lh-body)] text-[var(--text-accent)]">
          Drop files to attach — PDF, DOCX, XLSX, TXT or Markdown
        </p>
      ) : (
        <textarea
          className={cn(
            "max-h-48 min-h-[1.375rem] w-full resize-none bg-transparent outline-none",
            "text-[length:var(--text-size-body)] leading-[var(--text-lh-body)] text-[var(--text-primary)]",
            "placeholder:text-[var(--text-tertiary)]",
          )}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && canSend) {
              event.preventDefault();
              onSubmit?.();
            }
          }}
          placeholder={disabled ? "" : placeholder}
          rows={1}
          value={disabled ? "" : value}
        />
      )}

      {disabled && (
        <p className="text-[length:var(--text-size-body)] leading-[var(--text-lh-body)] text-[var(--text-tertiary)]">
          You have read-only access to this workspace
        </p>
      )}

      <div className="flex items-center gap-2">
        <button
          aria-label="Attach files"
          className={cn(
            "flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[var(--radius-sm)]",
            "bg-[var(--surface-base)] ring-1 ring-inset ring-[var(--border-subtle)]",
            "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
            disabled && "pointer-events-none text-[var(--text-tertiary)]",
          )}
          onClick={onAttach}
          type="button"
        >
          <Plus aria-hidden="true" size={18} />
        </button>

        {capabilities}

        <span className="flex-1" />

        {generating ? (
          <button
            aria-label="Stop generating"
            className={cn(
              "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full",
              "bg-[var(--text-primary)] text-[var(--surface-base)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
            )}
            onClick={onStop}
            type="button"
          >
            <span aria-hidden="true" className="h-[11px] w-[11px] rounded-[2.5px] bg-current" />
          </button>
        ) : (
          <button
            aria-label="Send message"
            className={cn(
              "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full",
              "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
              canSend
                ? "bg-[var(--accent-primary)] text-[var(--text-on-accent)] hover:bg-[var(--accent-hover)]"
                : "bg-[var(--status-neutral-bg)] text-[var(--text-tertiary)]",
            )}
            disabled={!canSend}
            onClick={onSubmit}
            type="button"
          >
            <ArrowUp aria-hidden="true" size={18} />
          </button>
        )}
      </div>

      {error && (
        <p className="flex items-center gap-2 pt-0.5 text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--status-danger-text)]">
          <X aria-hidden="true" className="shrink-0" size={16} />
          {error}
        </p>
      )}
      {disabledReason && (
        <p className="flex items-center gap-2 pt-0.5 text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
          <Lock aria-hidden="true" className="shrink-0" size={16} />
          {disabledReason}
        </p>
      )}
    </div>
  );
}
