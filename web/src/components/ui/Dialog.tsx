"use client";

import { cn } from "@/lib/cn";
import { X } from "lucide-react";
import { type RefObject, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

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
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    let backgroundElements: Array<{
      element: HTMLElement;
      ariaHidden: string | null;
      inert: boolean;
    }> = [];
    const frame = window.requestAnimationFrame(() => {
      const overlayRoot = dialogRef.current?.parentElement;
      backgroundElements = Array.from(document.body.children)
        .filter((element): element is HTMLElement => element instanceof HTMLElement && element !== overlayRoot)
        .map((element) => ({
          element,
          ariaHidden: element.getAttribute("aria-hidden"),
          inert: element.inert,
        }));
      for (const { element } of backgroundElements) {
        element.inert = true;
        element.setAttribute("aria-hidden", "true");
      }
      (initialFocusRef?.current ?? focusableElements(dialogRef.current)[0])?.focus();
    });
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(dialogRef.current);
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
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      for (const { element, ariaHidden, inert } of backgroundElements) {
        element.inert = inert;
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
      previouslyFocused?.focus();
    };
  }, [initialFocusRef, open]);

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
          "relative z-10 flex max-h-[calc(100dvh-2rem)] w-full max-w-lg flex-col overflow-hidden rounded-[var(--adm-r-lg)] bg-[var(--adm-raised)] shadow-[var(--adm-e3)]",
          "ui-dialog-panel",
          className
        )}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--adm-hairline)] px-4 py-3">
          <h2 id={titleId} className="text-[0.9375rem] font-semibold text-[var(--text)]">{title}</h2>
          <button
            aria-label="Close dialog"
            onClick={onClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--adm-r-sm)] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            type="button"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && (
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-[var(--adm-hairline)] bg-[var(--adm-inset)] px-4 py-3">
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
