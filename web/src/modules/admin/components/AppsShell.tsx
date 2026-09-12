"use client";

import Link from "next/link";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useState } from "react";

import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { ProductMark } from "@/components/ui/ProductMark";
import { ProductSidebarGlobalNavigation } from "@/components/ui/ProductSidebarGlobalNavigation";
import { ToastProvider } from "@/components/ui/Toast";
import { appBrand } from "@/lib/brand";
import { cn } from "@/lib/cn";

/** The Apps directory is a product surface, not a Workspace settings section. */
export function AppsShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <ToastProvider>
      <div className="apps-shell">
        <aside className={cn("apps-sidebar", collapsed && "apps-sidebar--collapsed")}>
          <div className="apps-sidebar__header">
            <Link aria-label={`${appBrand.productName} home`} className="apps-sidebar__brand" href="/app">
              <ProductMark decorative size="md" />
              {!collapsed && <span>{appBrand.productName}</span>}
            </Link>
            <button
              aria-label={collapsed ? "Expand Apps navigation" : "Collapse Apps navigation"}
              className="apps-sidebar__collapse"
              onClick={() => setCollapsed((value) => !value)}
              title={collapsed ? "Expand navigation" : "Collapse navigation"}
              type="button"
            >
              {collapsed ? <PanelLeftOpen aria-hidden="true" size={16} /> : <PanelLeftClose aria-hidden="true" size={16} />}
            </button>
          </div>
          <ProductSidebarGlobalNavigation collapsed={collapsed} />
          {!collapsed && (
            <div className="apps-sidebar__context">
              <p>Apps</p>
              <span>Integrations and governed actions</span>
            </div>
          )}
        </aside>
        <main className="apps-shell__main" id="main-content">{children}</main>
        <GlobalAssistantLauncher />
      </div>
    </ToastProvider>
  );
}
