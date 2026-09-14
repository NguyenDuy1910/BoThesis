"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { ToastProvider } from "@/components/ui/Toast";
import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { useShellNav } from "@/components/shell/useShellNav";
import {
  AdminBreadcrumbProvider,
  useAdminBreadcrumb,
} from "@/modules/admin/breadcrumb";
import { AdminWorkspaceProvider } from "@/modules/admin/workspace";
import { modeForPath } from "@/lib/navigation";
import { PlatformAdminRail, WorkspaceAdminRail } from "@/components/rails";

import { AdminCommandPalette } from "./AdminCommandPalette";
import { AdminTopbar } from "./AdminTopbar";

export function AdminShell({ children }: { children: React.ReactNode }) {
  const nav = useShellNav();
  const [searchOpen, setSearchOpen] = useState(false);

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
            collapsed={nav.collapsed}
            mobileOpen={nav.mobileOpen}
            onCloseMobile={nav.closeMobile}
            onExpand={nav.expand}
            onOpenMobile={nav.openMobile}
            onSearchClose={() => setSearchOpen(false)}
            onSearchOpen={() => setSearchOpen(true)}
            onToggleCollapsed={nav.toggleCollapsed}
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
  const pathname = usePathname();
  const isPlatform = modeForPath(pathname) === "platform-admin";

  return (
    <div className="shell">
      {isPlatform ? (
        <PlatformAdminRail
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          onMobileClose={onCloseMobile}
          onToggleCollapse={onToggleCollapsed}
        />
      ) : (
        <WorkspaceAdminRail
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          onMobileClose={onCloseMobile}
          onToggleCollapse={onToggleCollapsed}
        />
      )}
      <div className="shell__main">
        <AdminTopbar
          collapsed={collapsed}
          detailTitle={detailTitle}
          onExpand={onExpand}
          onMobileMenuOpen={onOpenMobile}
          onSearchOpen={onSearchOpen}
        />
        <main className="shell__scroll" id="main-content">
          <div className="shell__page shell__route-outlet" key={pathname}>{children}</div>
        </main>
      </div>
      <AdminCommandPalette onClose={onSearchClose} open={searchOpen} />
      <GlobalAssistantLauncher />
    </div>
  );
}
