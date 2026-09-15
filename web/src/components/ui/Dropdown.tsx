"use client";

import { cn } from "@/lib/cn";
import { ChevronDown } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface DropdownProps {
  label: React.ReactNode;
  children: React.ReactNode;
  align?: "left" | "right";
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  buttonClassName?: string;
  menuClassName?: string;
  showChevron?: boolean;
  title?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  closeOnScroll?: boolean;
}

interface MenuPosition {
  top: number;
  left: number;
  maxHeight: number;
  openUp: boolean;
}

const MENU_GAP = 8;
const VIEWPORT_MARGIN = 8;

const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

export function Dropdown({
  label,
  children,
  align = "right",
  disabled,
  ariaLabel,
  className,
  buttonClassName,
  menuClassName,
  showChevron = true,
  title,
  open: controlledOpen,
  onOpenChange,
  closeOnScroll = false,
}: DropdownProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const open = controlledOpen ?? internalOpen;
  const menuId = useId();
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const triggerButtonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const initialFocusRef = useRef<"first" | "last">("first");

  const setOpen = useCallback((nextOpen: boolean) => {
    if (!nextOpen) setClosing(true);
    if (controlledOpen === undefined) setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  }, [controlledOpen, onOpenChange]);

  // Hold the node through the exit animation, then drop it.
  useEffect(() => {
    if (open || !closing) return;
    const timer = window.setTimeout(() => setClosing(false), 110);
    return () => window.clearTimeout(timer);
  }, [closing, open]);

  // Anchor the menu to the trigger in viewport coordinates so a portal-rendered
  // menu can never be clipped by an ancestor's overflow (tables, scroll panes).
  const computePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const menuHeight = menuRef.current?.offsetHeight ?? 0;
    const menuWidth = menuRef.current?.offsetWidth ?? 192;
    const openUp = menuHeight > 0 && spaceBelow < menuHeight + MENU_GAP && spaceAbove > spaceBelow;
    const available = (openUp ? spaceAbove : spaceBelow) - MENU_GAP - VIEWPORT_MARGIN;
    const preferredLeft = align === "right" ? rect.right - menuWidth : rect.left;
    const next: MenuPosition = {
      top: openUp ? rect.top - MENU_GAP - menuHeight : rect.bottom + MENU_GAP,
      left: Math.min(
        Math.max(VIEWPORT_MARGIN, preferredLeft),
        Math.max(VIEWPORT_MARGIN, window.innerWidth - menuWidth - VIEWPORT_MARGIN),
      ),
      maxHeight: Math.max(120, available),
      openUp,
    };
    setPosition(next);
  }, [align]);

  useIsomorphicLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    computePosition();
    const handleScroll = () => {
      if (closeOnScroll) setOpen(false);
      else computePosition();
    };
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", computePosition);
    return () => {
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", computePosition);
    };
  }, [closeOnScroll, computePosition, open, setOpen]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      const items = enabledMenuItems(menuRef.current);
      const target = initialFocusRef.current === "last" ? items.at(-1) : items[0];
      target?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerButtonRef.current?.focus();
      }
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, setOpen]);

  const menuStyle: React.CSSProperties = position
    ? {
        position: "fixed",
        top: position.top,
        left: position.left,
        maxHeight: position.maxHeight,
        visibility: "visible",
      }
    : { position: "fixed", top: -9999, left: -9999, visibility: "hidden" };

  return (
    <div ref={triggerRef} className={cn("relative inline-flex", className)}>
      <button
        ref={triggerButtonRef}
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-controls={open ? menuId : undefined}
        aria-expanded={open}
        aria-haspopup="menu"
        title={title}
        onClick={() => {
          initialFocusRef.current = "first";
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
          event.preventDefault();
          initialFocusRef.current = event.key === "ArrowUp" ? "last" : "first";
          setOpen(true);
        }}
        className={cn(
          "inline-flex h-9 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--surface-base)] px-3 text-[length:var(--text-size-ui)] font-medium text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--border-default)] transition-[background-color,color,box-shadow] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] hover:shadow-[inset_0_0_0_1px_var(--border-default)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-canvas)] disabled:pointer-events-none disabled:opacity-45",
          buttonClassName
        )}
      >
        {label}
        {showChevron && <ChevronDown aria-hidden="true" className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />}
      </button>
      {(open || closing) &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            id={menuId}
            ref={menuRef}
            role="menu"
            onClick={(event) => {
              if ((event.target as HTMLElement).closest('[role="menuitem"]')) {
                setOpen(false);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === "Tab") setOpen(false);
              else handleMenuKeyDown(event, menuRef.current);
            }}
            data-placement={position?.openUp ? "top" : "bottom"}
            data-state={open ? "open" : "closed"}
            style={menuStyle}
            className={cn(
              "ui-popover z-[60] min-w-52 overflow-y-auto overscroll-contain rounded-[var(--radius-md)] bg-[var(--surface-raised)] p-1 shadow-[var(--elevation-3)]",
              !open && "pointer-events-none",
              menuClassName
            )}
          >
            {children}
          </div>,
          document.body
        )}
    </div>
  );
}

function enabledMenuItems(menu: HTMLDivElement | null) {
  if (!menu) return [];
  return Array.from(
    menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'),
  );
}

function handleMenuKeyDown(
  event: React.KeyboardEvent<HTMLDivElement>,
  menu: HTMLDivElement | null,
) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  const items = enabledMenuItems(menu);
  if (!items.length) return;
  event.preventDefault();
  const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
  if (event.key === "Home") items[0]?.focus();
  else if (event.key === "End") items.at(-1)?.focus();
  else {
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = currentIndex < 0
      ? delta > 0 ? 0 : items.length - 1
      : (currentIndex + delta + items.length) % items.length;
    items[nextIndex]?.focus();
  }
}

interface DropdownItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  destructive?: boolean;
  selected?: boolean;
}

export function DropdownItem({
  destructive,
  selected,
  className,
  type = "button",
  ...props
}: DropdownItemProps) {
  return (
    <button
      type={type}
      role="menuitem"
      className={cn(
        "text-[length:var(--text-size-ui)]",
        "flex min-h-9 w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        destructive
          ? "text-[var(--status-danger-text)] hover:bg-[var(--status-danger-bg)]"
          : selected
            ? "bg-[var(--surface-selected)] text-[var(--text-accent)]"
            : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
        "disabled:pointer-events-none disabled:text-[var(--text-tertiary)] disabled:opacity-50 disabled:hover:bg-transparent",
        className
      )}
      {...props}
    />
  );
}

/** Non-interactive grouping label inside a menu. */
export function DropdownLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-2 text-[length:var(--text-size-caption)] font-semibold uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
      {children}
    </p>
  );
}

export function DropdownSeparator() {
  return <div className="my-1 h-px bg-[var(--border-subtle)]" role="separator" />;
}
