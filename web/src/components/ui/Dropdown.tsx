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
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const open = controlledOpen ?? internalOpen;
  const menuId = useId();
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const triggerButtonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const initialFocusRef = useRef<"first" | "last">("first");

  const setOpen = useCallback((nextOpen: boolean) => {
    if (controlledOpen === undefined) setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  }, [controlledOpen, onOpenChange]);

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
      top: openUp ? rect.top - MENU_GAP : rect.bottom + MENU_GAP,
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
        transform: position.openUp ? "translateY(-100%)" : undefined,
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
          "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/25 disabled:pointer-events-none disabled:bg-slate-100 disabled:text-slate-400",
          buttonClassName
        )}
      >
        {label}
        {showChevron && <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />}
      </button>
      {open &&
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
            style={menuStyle}
            className={cn(
              "z-[60] min-w-48 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-xl shadow-slate-950/10",
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
        "flex min-h-8 w-full items-center gap-2 rounded-md px-2.5 text-left text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20",
        destructive
          ? "text-red-700 hover:bg-red-50"
          : selected
            ? "bg-teal-50 text-teal-800"
            : "text-slate-700 hover:bg-slate-50 hover:text-slate-950",
        "disabled:pointer-events-none disabled:text-slate-400 disabled:hover:bg-transparent",
        className
      )}
      {...props}
    />
  );
}
