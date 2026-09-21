"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { ToastProvider } from "@/components/ui/Toast";
import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { useShellNav } from "@/components/shell/useShellNav";
import {
  WorkspaceBreadcrumbProvider,
  useWorkspaceBreadcrumb,
} from "@/modules/workspace-control/breadcrumb";
import { WorkspaceControlProvider } from "@/modules/workspace-control/workspace";
import { modeForPath } from "@/lib/navigation";
import { PlatformControlRail, WorkspaceControlRail } from "@/components/rails";

import { ControlPlaneCommandPalette } from "./ControlPlaneCommandPalette";
import { ControlPlaneTopbar } from "./ControlPlaneTopbar";

export function ControlPlaneShell({ children }: { children: React.ReactNode }) {
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
    <WorkspaceControlProvider>
      <WorkspaceBreadcrumbProvider>
        <ToastProvider>
          <ControlPlaneFrame
            collapsed={nav.collapsed}
            mobileOpen={nav.mobileOpen}
            onCloseMobile={nav.closeMobile}
            onExpand={nav.expand}
            onOpenMobile={nav.openMobile}
            onSearchClose={() => setSearchOpen(false)}
            onToggleCollapsed={nav.toggleCollapsed}
            searchOpen={searchOpen}
          >
            {children}
          </ControlPlaneFrame>
        </ToastProvider>
      </WorkspaceBreadcrumbProvider>
    </WorkspaceControlProvider>
  );
}

interface ControlPlaneFrameProps {
  children: React.ReactNode;
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onExpand: () => void;
  onOpenMobile: () => void;
  onSearchClose: () => void;
  onToggleCollapsed: () => void;
  searchOpen: boolean;
}

function ControlPlaneFrame({
  children,
  collapsed,
  mobileOpen,
  onCloseMobile,
  onExpand,
  onOpenMobile,
  onSearchClose,
  onToggleCollapsed,
  searchOpen,
}: ControlPlaneFrameProps) {
  const { detailTitle } = useWorkspaceBreadcrumb();
  const pathname = usePathname();
  const isPlatform = modeForPath(pathname) === "platform-control";

  return (
    <div className="shell">
      {isPlatform ? (
        <PlatformControlRail
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          onMobileClose={onCloseMobile}
          onToggleCollapse={onToggleCollapsed}
        />
      ) : (
        <WorkspaceControlRail
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          onMobileClose={onCloseMobile}
          onToggleCollapse={onToggleCollapsed}
        />
      )}
      <div className="shell__main">
        <ControlPlaneTopbar
          collapsed={collapsed}
          detailTitle={detailTitle}
          onExpand={onExpand}
          onMobileMenuOpen={onOpenMobile}
        />
        <main className="shell__scroll" id="main-content">
          <div className="shell__page shell__route-outlet" key={pathname}>{children}</div>
        </main>
      </div>
      <ControlPlaneCommandPalette onClose={onSearchClose} open={searchOpen} />
      <GlobalAssistantLauncher />
    </div>
  );
}
