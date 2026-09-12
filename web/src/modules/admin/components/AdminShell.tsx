"use client";

import { useCallback, useEffect, useState } from "react";

import { ToastProvider } from "@/components/ui/Toast";
import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { useLocalStorage } from "@/lib/hooks/useLocalStorage";
import {
  AdminBreadcrumbProvider,
  useAdminBreadcrumb,
} from "@/modules/admin/breadcrumb";
import { AdminWorkspaceProvider } from "@/modules/admin/workspace";

import { AdminCommandPalette } from "./AdminCommandPalette";
import { AdminSidebar } from "./AdminSidebar";
import { AdminTopbar } from "./AdminTopbar";

export function AdminShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useLocalStorage("bothesis-admin-nav", false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <AdminWorkspaceProvider>
      <AdminBreadcrumbProvider>
        <ToastProvider>
          <AdminFrame
            collapsed={collapsed}
            mobileOpen={mobileOpen}
            onCloseMobile={closeMobile}
            onExpand={() => setCollapsed(false)}
            onOpenMobile={() => setMobileOpen(true)}
            onSearchClose={() => setSearchOpen(false)}
            onSearchOpen={() => setSearchOpen(true)}
            onToggleCollapsed={() => setCollapsed(!collapsed)}
            searchOpen={searchOpen}
          >
            {children}
          </AdminFrame>
        </ToastProvider>
      </AdminBreadcrumbProvider>
    </AdminWorkspaceProvider>
  );
}

interface AdminFrameProps {
  children: React.ReactNode;
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onExpand: () => void;
  onOpenMobile: () => void;
  onSearchClose: () => void;
  onSearchOpen: () => void;
  onToggleCollapsed: () => void;
  searchOpen: boolean;
}

function AdminFrame({
  children,
  collapsed,
  mobileOpen,
  onCloseMobile,
  onExpand,
  onOpenMobile,
  onSearchClose,
  onSearchOpen,
  onToggleCollapsed,
  searchOpen,
}: AdminFrameProps) {
  const { detailTitle } = useAdminBreadcrumb();

  return (
    <div className="adm">
      <AdminSidebar
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onMobileClose={onCloseMobile}
        onToggle={onToggleCollapsed}
      />
      <div className="adm__main">
        <AdminTopbar
          collapsed={collapsed}
          detailTitle={detailTitle}
          onExpand={onExpand}
          onMobileMenuOpen={onOpenMobile}
          onSearchOpen={onSearchOpen}
        />
        <main className="adm__scroll" id="main-content">
          <div className="adm__page">{children}</div>
        </main>
      </div>
      <AdminCommandPalette onClose={onSearchClose} open={searchOpen} />
      <GlobalAssistantLauncher />
    </div>
  );
}
