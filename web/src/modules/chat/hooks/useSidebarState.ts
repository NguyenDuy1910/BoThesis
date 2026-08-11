"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "bothesis-sidebar-collapsed";

export interface SidebarState {
  collapsed: boolean;
  mobileOpen: boolean;
  toggleCollapse: () => void;
  openMobile: () => void;
  closeMobile: () => void;
}

export function useSidebarState(): SidebarState {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  });
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggleCollapse = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, String(next));
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
