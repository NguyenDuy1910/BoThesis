"use client";

import { useCallback, useEffect, useState } from "react";

import { useLocalStorage } from "@/lib/hooks/useLocalStorage";

/** `--bp-nav` in tokens.css, which is also Tailwind's `lg`. One value drives
 *  the CSS that moves the rail, the utilities that swap its controls, and
 *  this hook — so they cannot disagree about where the layout changes. */
const NAV_BREAKPOINT = "(max-width: 1023.98px)";

/**
 * One navigation state for every shell.
 *
 * Collapse is a deliberate desktop preference and persists; the mobile overlay
 * is transient and closes on navigation or on growing past the breakpoint. The
 * single stored key means collapsing the rail in chat leaves it collapsed in
 * workspace settings, which is what a person expects from one product.
 */
export function useShellNav() {
  const [collapsed, setCollapsed] = useLocalStorage("bothesis-nav-collapsed", false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isNarrow, setIsNarrow] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(NAV_BREAKPOINT);
    const sync = () => {
      setIsNarrow(query.matches);
      if (!query.matches) setMobileOpen(false);
    };
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const openMobile = useCallback(() => setMobileOpen(true), []);
  const toggleCollapsed = useCallback(
    () => setCollapsed(!collapsed),
    [collapsed, setCollapsed],
  );

  return {
    /** Below the breakpoint the rail is an overlay and always shows labels. */
    collapsed: collapsed && !isNarrow,
    isNarrow,
    mobileOpen,
    openMobile,
    closeMobile,
    toggleCollapsed,
    expand: useCallback(() => setCollapsed(false), [setCollapsed]),
  };
}
