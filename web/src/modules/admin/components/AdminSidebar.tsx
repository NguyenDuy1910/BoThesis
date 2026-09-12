"use client";

import {
  PanelLeftClose,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ProductMark } from "@/components/ui/ProductMark";
import { ProductSidebarGlobalNavigation } from "@/components/ui/ProductSidebarGlobalNavigation";
import { appBrand } from "@/lib/brand";
import { cn } from "@/lib/cn";
import { getAuthSession } from "@/lib/auth/session";
import {
  adminNavGroupLabels,
  type AdminRoute,
  visibleAdminNavGroups,
} from "@/modules/admin/navigation";
import { useAdminWorkspace } from "@/modules/admin/workspace";

import { AdminAccountMenu } from "./AdminAccountMenu";

interface AdminSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function AdminSidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: AdminSidebarProps) {
  const pathname = usePathname();
  const { tenant, attentionCount } = useAdminWorkspace();
  const navigationGroups = visibleAdminNavGroups(getAuthSession());
  // On mobile the panel is an overlay, so it always shows its full width.
  const compact = collapsed && !mobileOpen;

  const isActive = (route: AdminRoute) =>
    route.path === "/admin"
      ? pathname === "/admin"
      : route.id === "platform-overview"
        ? pathname === route.path
      : pathname === route.path || pathname.startsWith(`${route.path}/`);

  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Close navigation"
          className="adm-nav__scrim"
          onClick={onMobileClose}
          type="button"
        />
      )}

      <nav
        aria-label="Admin"
        className={cn(
          "adm-nav",
          compact && "adm-nav--collapsed",
          mobileOpen && "adm-nav--open",
        )}
      >
        <div className="adm-nav__brand">
          <Link
            aria-label={`${appBrand.productName} workspace`}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-sm)] px-1 py-1 transition-colors hover:bg-[var(--surface-hover)]"
            href="/admin"
            onClick={onMobileClose}
          >
            <ProductMark decorative size="md" />
            {!compact && (
              <span className="adm-nav__wordmark">
                <strong>{appBrand.productName}</strong>
                <span>{tenant?.name ?? "Workspace"}</span>
              </span>
            )}
          </Link>
          {!compact && (
            <button
              aria-label="Collapse navigation"
              className="hidden h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] md:inline-flex"
              onClick={onToggle}
              type="button"
            >
              <PanelLeftClose aria-hidden="true" size={15} />
            </button>
          )}
          <button
            aria-label="Close navigation"
            className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] md:hidden"
            onClick={onMobileClose}
            type="button"
          >
            <X aria-hidden="true" size={16} />
          </button>
        </div>

        <div className="adm-nav__scroll">
          <ProductSidebarGlobalNavigation collapsed={compact} onNavigate={onMobileClose} />
          {navigationGroups.map((group) => {
            const label = group.id === "workspace"
              ? `${adminNavGroupLabels[group.id]} · ${(tenant?.name ?? "Workspace").toUpperCase()}`
              : adminNavGroupLabels[group.id];
            if (!group.routes.length) return null;
            return (
              <div className="adm-nav__group" key={group.id}>
                {label && <p className="adm-nav__label">{label}</p>}
                <div className="adm-nav__items">
                  {group.routes.map((route) => {
                    const Icon = route.icon;
                    const active = isActive(route);
                    const badge =
                      route.id === "members" && attentionCount > 0
                        ? attentionCount
                        : undefined;
                    return (
                      <Link
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "adm-nav__item",
                          active && "adm-nav__item--active",
                        )}
                        href={route.path}
                        key={route.id}
                        onClick={onMobileClose}
                        title={compact ? route.label : undefined}
                      >
                        <Icon aria-hidden="true" size={16} />
                        {!compact && <span>{route.label}</span>}
                        {!compact && badge !== undefined && (
                          <span className="adm-nav__count">{badge}</span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="adm-nav__footer">
          <AdminAccountMenu compact={compact} />
        </div>
      </nav>
    </>
  );
}
