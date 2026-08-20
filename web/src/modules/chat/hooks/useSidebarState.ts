"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "bothesis-sidebar-collapsed";

function readCollapsedState(): boolean {
  if (typeof window === "undefined") return false;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === null) return false;
  try {
    const value: unknown = JSON.parse(stored);
    return typeof value === "boolean" ? value : false;
  } catch {
    return false;
  }
}

export interface SidebarState {
  collapsed: boolean;
  mobileOpen: boolean;
  toggleCollapse: () => void;
  openMobile: () => void;
  closeMobile: () => void;
}

export function useSidebarState(): SidebarState {
  const [collapsed, setCollapsed] = useState(readCollapsedState);
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggleCollapse = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const openMobile = useCallback(() => setMobileOpen(true), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 820px)");
    const handler = () => {
      if (!mql.matches) setMobileOpen(false);
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return { collapsed, mobileOpen, toggleCollapse, openMobile, closeMobile };
}
