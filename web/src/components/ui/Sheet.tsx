"use client";

import { cn } from "@/lib/cn";
import { X } from "lucide-react";
import { type RefObject, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
}

/** A keyboard-safe side sheet for focused, in-context setup work. */
export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
  className,
  initialFocusRef,
}: SheetProps) {
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => {
      (initialFocusRef?.current ?? focusableElements(sheetRef.current)[0])?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(sheetRef.current);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = "";
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [initialFocusRef, open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
      <button
        aria-label="Close setup panel"
        className="ui-sheet-scrim absolute inset-0 cursor-default bg-slate-950/30"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        ref={sheetRef}
        aria-labelledby={titleId}
        aria-modal="true"
        className={cn(
          "relative z-10 flex h-full w-full max-w-xl flex-col overflow-hidden border-l border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-popover)]",
          "ui-sheet-panel",
          className,
        )}
        role="dialog"
      >
        <div className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-5 sm:px-6">
          <h2 className="min-w-0 text-base font-semibold text-[var(--text)]" id={titleId}>{title}</h2>
          <button
            aria-label="Close setup panel"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            onClick={onClose}
            type="button"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
        {footer && <div className="shrink-0 border-t border-[var(--border)] bg-[var(--bg-panel)] px-5 py-3 sm:px-6">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

function focusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden"));
}
