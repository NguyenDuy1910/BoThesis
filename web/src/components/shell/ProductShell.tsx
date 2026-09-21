"use client";

import { createContext, use, useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import { WorkspaceRail } from "@/components/rails";
import { useShellNav } from "@/components/shell/useShellNav";
import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { ToastProvider } from "@/components/ui/Toast";

interface ProductShellNavigation {
  collapsed: boolean;
  closeMobile: () => void;
  mobileOpen: boolean;
  openMobile: () => void;
}

interface ProductShellSidebar {
  setSidebarContent: (content: React.ReactNode) => void;
}

const ProductShellNavigationContext = createContext<ProductShellNavigation | null>(null);
const ProductShellSidebarContext = createContext<ProductShellSidebar | null>(null);

/**
 * Gives a feature access to the persistent product rail's mobile controls.
 * Feature content never creates its own shell or sidebar.
 */
export function useProductShellNavigation() {
  const value = use(ProductShellNavigationContext);
  if (!value) throw new Error("useProductShellNavigation must be used inside ProductShell.");
  return value;
}

/**
 * Lets Chat contribute its recent-conversation list below the permanent
 * product navigation without owning or remounting the sidebar itself.
 */
export function useProductShellSidebar() {
  const value = use(ProductShellSidebarContext);
  if (!value) throw new Error("useProductShellSidebar must be used inside ProductShell.");
  return value;
}

/**
 * The durable User Workspace layout. Route children replace only the outlet;
 * the rail, account control and toast layer stay mounted, so moving between
 * places re-renders the main area alone.
 */
export function ProductShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const nav = useShellNav();
  const [sidebarContent, setSidebarContent] = useState<React.ReactNode>(null);
  const navigation = useMemo<ProductShellNavigation>(
    () => ({
      collapsed: nav.collapsed,
      closeMobile: nav.closeMobile,
      mobileOpen: nav.mobileOpen,
      openMobile: nav.openMobile,
    }),
    [nav.collapsed, nav.closeMobile, nav.mobileOpen, nav.openMobile],
  );
  const sidebar = useMemo<ProductShellSidebar>(
    () => ({ setSidebarContent }),
    [],
  );
  const isChat = pathname === "/app";
  // Library is URL-addressable by view. It gets the same outlet transition
  // without making chat action query parameters remount a live conversation.
  const routeKey = pathname === "/library"
    ? `${pathname}?view=${searchParams.get("view") ?? ""}`
    : pathname;

  return (
    <ProductShellNavigationContext value={navigation}>
      <ProductShellSidebarContext value={sidebar}>
        <ToastProvider>
          <div className="shell">
            <WorkspaceRail
              collapsed={nav.collapsed}
              mobileOpen={nav.mobileOpen}
              onMobileClose={nav.closeMobile}
              onToggleCollapse={nav.toggleCollapsed}
            >
              {sidebarContent}
            </WorkspaceRail>

            <div className="shell__main" id="main-content">
              {isChat ? (
                <RouteOutlet routeKey={routeKey}>{children}</RouteOutlet>
              ) : (
                <div className="shell__scroll">
                  <RouteOutlet routeKey={routeKey}>{children}</RouteOutlet>
                </div>
              )}
            </div>
            {!isChat && <GlobalAssistantLauncher />}
          </div>
        </ToastProvider>
      </ProductShellSidebarContext>
    </ProductShellNavigationContext>
  );
}

function RouteOutlet({ children, routeKey }: { children: React.ReactNode; routeKey: string }) {
  return (
    <div className="shell__route-outlet" key={routeKey}>
      {children}
    </div>
  );
}
