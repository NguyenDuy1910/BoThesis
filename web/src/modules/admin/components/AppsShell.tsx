"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getAuthSession, hasAnySessionPermission, type AuthSession } from "@/lib/auth/session";
import { appBrand } from "@/lib/brand";
import { cn } from "@/lib/cn";
import { isProductNavigationActive, productNavigationItems } from "@/lib/product-navigation";

/** The Apps surface has its own product navigation in the canonical design. */
export function AppsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => setSession(getAuthSession()), []);
  const destinations = productNavigationItems.filter(
    (destination) => !destination.permissionCodes || hasAnySessionPermission(session, destination.permissionCodes),
  );

  return (
    <div className="apps-shell">
      <aside className="apps-sidebar">
        <Link aria-label={`${appBrand.productName} home`} className="apps-sidebar__brand" href="/app">
          {appBrand.productName}
        </Link>
        <nav aria-label="Product" className="apps-sidebar__nav">
          {destinations.map(({ href, icon: Icon, label }) => {
            const active = isProductNavigationActive(pathname, href);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={cn("apps-sidebar__link", active && "apps-sidebar__link--active")}
                href={href}
                key={label}
              >
                <Icon aria-hidden="true" size={16} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="apps-sidebar__your-apps">
          <p>YOUR APPS</p>
          <span><i className="apps-status-dot" />Connected apps appear here</span>
        </div>
        <div className="apps-sidebar__account">
          <span aria-hidden="true">D</span>
          <div><strong>Workspace</strong><small>Personal workspace</small></div>
        </div>
      </aside>
      <main className="apps-shell__main" id="main-content">{children}</main>
    </div>
  );
}
