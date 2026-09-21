"use client";

import { type RefObject, useEffect, useRef } from "react";

function focusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden"));
}

interface ModalLayerOptions {
  open: boolean;
  onClose: () => void;
  /** The panel itself. Everything outside it becomes inert while open. */
  panelRef: RefObject<HTMLElement | null>;
  /** Where focus should land; defaults to the first focusable in the panel. */
  initialFocusRef?: RefObject<HTMLElement | null>;
}

/**
 * Everything a layer above the page owes a keyboard and screen-reader user:
 * the page behind it goes inert, focus moves in and cycles inside, Escape
 * closes, body scroll is locked, and focus returns where it came from.
 *
 * Dialogs, sheets and the contextual inspector all need exactly this, and had
 * each grown their own copy of it. One implementation means a fix to the trap
 * reaches every layer instead of one.
 */
export function useModalLayer({
  open,
  onClose,
  panelRef,
  initialFocusRef,
}: ModalLayerOptions) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    let background: Array<{
      element: HTMLElement;
      ariaHidden: string | null;
      inert: boolean;
    }> = [];

    document.body.style.overflow = "hidden";

    // Deferred a frame so the portal has been inserted and can be excluded
    // from the set of elements being made inert.
    const frame = window.requestAnimationFrame(() => {
      const overlayRoot = panelRef.current?.closest("body > *");
      background = Array.from(document.body.children)
        .filter(
          (element): element is HTMLElement =>
            element instanceof HTMLElement && element !== overlayRoot,
        )
        .map((element) => ({
          element,
          ariaHidden: element.getAttribute("aria-hidden"),
          inert: element.inert,
        }));
      for (const { element } of background) {
        element.inert = true;
        element.setAttribute("aria-hidden", "true");
      }
      (initialFocusRef?.current ?? focusableElements(panelRef.current)[0])?.focus();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(panelRef.current);
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
      for (const { element, ariaHidden, inert } of background) {
        element.inert = inert;
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      }
      previouslyFocused?.focus();
    };
  }, [initialFocusRef, open, panelRef]);
}
