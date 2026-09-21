"use client";

import { cn } from "@/lib/cn";
import { X } from "lucide-react";
import { type RefObject, useId, useRef } from "react";
import { createPortal } from "react-dom";

import { useModalLayer } from "@/lib/hooks/useModalLayer";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  className,
  initialFocusRef,
}: DialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useModalLayer({ initialFocusRef, onClose, open, panelRef: dialogRef });

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        aria-label="Close dialog"
        className="fixed inset-0 cursor-default bg-[var(--overlay-scrim)]"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        ref={dialogRef}
        aria-modal="true"
        role="dialog"
        aria-labelledby={titleId}
        className={cn(
          "relative z-10 flex max-h-[calc(100dvh-2rem)] w-full max-w-lg flex-col overflow-hidden rounded-[var(--radius-lg)] bg-[var(--surface-raised)] shadow-[var(--elevation-3)]",
          "ui-dialog-panel",
          className
        )}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-3">
          <h2 id={titleId} className="text-[length:var(--text-size-body)] font-semibold text-[var(--text-primary)]">{title}</h2>
          <button
            aria-label="Close dialog"
            onClick={onClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            type="button"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && (
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-[var(--border-subtle)] bg-[var(--surface-inset)] px-4 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

function focusableElements(container: HTMLDivElement | null) {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(
    'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
  ));
}
