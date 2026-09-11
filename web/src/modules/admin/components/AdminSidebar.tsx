"use client";

import { ArrowUpRight, PanelLeftClose, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ProductMark } from "@/components/ui/ProductMark";
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
            aria-label={`${appBrand.productName} Admin dashboard`}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-[var(--adm-r-sm)] px-1 py-1 transition-colors hover:bg-[var(--adm-row-hover)]"
            href="/admin"
            onClick={onMobileClose}
          >
            <ProductMark decorative size="md" />
            {!compact && (
              <span className="adm-nav__wordmark">
                <strong>{tenant?.name ?? appBrand.productName}</strong>
                <span>Admin</span>
              </span>
            )}
          </Link>
          {!compact && (
            <button
              aria-label="Collapse navigation"
              className="hidden h-7 w-7 items-center justify-center rounded-[var(--adm-r-sm)] text-[var(--text-muted)] transition-colors hover:bg-[var(--adm-row-hover)] hover:text-[var(--text)] md:inline-flex"
              onClick={onToggle}
              type="button"
            >
              <PanelLeftClose aria-hidden="true" size={15} />
            </button>
          )}
          <button
            aria-label="Close navigation"
            className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--adm-r-sm)] text-[var(--text-muted)] transition-colors hover:bg-[var(--adm-row-hover)] hover:text-[var(--text)] md:hidden"
            onClick={onMobileClose}
            type="button"
          >
            <X aria-hidden="true" size={16} />
          </button>
        </div>

        <div className="adm-nav__scroll">
          {navigationGroups.map((group) => {
            const label = adminNavGroupLabels[group.id];
            if (!group.routes.length) return null;
            return (
              <div className="adm-nav__group" key={group.id}>
                {label && <p className="adm-nav__label">{label}</p>}
                <div className="adm-nav__items">
                  {group.routes.map((route) => {
                    const Icon = route.icon;
                    const active = isActive(route);
                    const badge =
                      route.id === "access" && attentionCount > 0
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
                        {!compact && route.external && (
                          <ArrowUpRight
                            aria-hidden="true"
                            className="adm-nav__external"
                            size={13}
                          />
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
