"use client";

import { cn } from "@/lib/cn";
import { ChevronDown } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
}

interface MenuPosition {
  top: number;
  left?: number;
  right?: number;
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
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Anchor the menu to the trigger in viewport coordinates so a portal-rendered
  // menu can never be clipped by an ancestor's overflow (tables, scroll panes).
  const computePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const menuHeight = menuRef.current?.offsetHeight ?? 0;
    const openUp = menuHeight > 0 && spaceBelow < menuHeight + MENU_GAP && spaceAbove > spaceBelow;
    const available = (openUp ? spaceAbove : spaceBelow) - MENU_GAP - VIEWPORT_MARGIN;
    const next: MenuPosition = {
      top: openUp ? rect.top - MENU_GAP : rect.bottom + MENU_GAP,
      maxHeight: Math.max(120, available),
      openUp,
    };
    if (align === "right") next.right = window.innerWidth - rect.right;
    else next.left = rect.left;
    setPosition(next);
  }, [align]);

  useIsomorphicLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    computePosition();
    const reposition = () => computePosition();
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open, computePosition]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const menuStyle: React.CSSProperties = position
    ? {
        position: "fixed",
        top: position.top,
        left: position.left,
        right: position.right,
        maxHeight: position.maxHeight,
        transform: position.openUp ? "translateY(-100%)" : undefined,
        visibility: "visible",
      }
    : { position: "fixed", top: -9999, left: -9999, visibility: "hidden" };

  return (
    <div ref={triggerRef} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="menu"
        title={title}
        onClick={() => setOpen((value) => !value)}
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
            ref={menuRef}
            role="menu"
            onClick={(event) => {
              if ((event.target as HTMLElement).closest('[role="menuitem"]')) {
                setOpen(false);
              }
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
