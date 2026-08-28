"use client";

import { ChevronLeft, Menu, MessageSquareText, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ProductMark } from "@/components/ui/ProductMark";
import { appBrand } from "@/lib/brand";
import { cn } from "@/lib/cn";
import { adminNavGroups } from "@/modules/admin/navigation";

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
  const visuallyCollapsed = collapsed && !mobileOpen;
  const isActive = (href: string) => (
    href === "/admin/overview" ? pathname === href : pathname.startsWith(href)
  );

  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Close admin navigation"
          className="admin-sidebar__scrim"
          onClick={onMobileClose}
          type="button"
        />
      )}

      <aside
        className={cn(
          "admin-sidebar",
          visuallyCollapsed && "admin-sidebar--collapsed",
          mobileOpen && "admin-sidebar--mobile-open",
        )}
      >
        <div className="admin-sidebar__header">
          {!visuallyCollapsed ? (
            <div className="admin-sidebar__brand">
              <ProductMark decorative size="md" />
              <span>
                <strong>{appBrand.productName}</strong>
                <small>{appBrand.adminName}</small>
              </span>
            </div>
          ) : (
            <button
              aria-label="Expand admin navigation"
              className="admin-sidebar__icon-button admin-sidebar__mark-button"
              onClick={onToggle}
              title="Expand navigation"
              type="button"
            >
              <ProductMark decorative size="md" />
            </button>
          )}
          {!visuallyCollapsed && (
            <button
              aria-label="Collapse admin navigation"
              className="admin-sidebar__icon-button admin-sidebar__collapse"
              onClick={onToggle}
              title="Collapse navigation"
              type="button"
            >
              <ChevronLeft aria-hidden="true" size={15} />
            </button>
          )}
          <button
            aria-label="Close admin navigation"
            className="admin-sidebar__icon-button admin-sidebar__close"
            onClick={onMobileClose}
            type="button"
          >
            <X aria-hidden="true" size={17} />
          </button>
        </div>

        <nav aria-label="Administration" className="admin-sidebar__nav">
          {adminNavGroups.map((group, groupIndex) => (
            <div className="admin-sidebar__group" key={group.label ?? groupIndex}>
              {group.label && !visuallyCollapsed && (
                <p className="admin-sidebar__group-label">{group.label}</p>
              )}
              <div className="admin-sidebar__items">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item.href);
                  return (
                    <Link
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "admin-sidebar__item",
                        active && "admin-sidebar__item--active",
                        visuallyCollapsed && "admin-sidebar__item--collapsed",
                      )}
                      href={item.href}
                      key={item.href}
                      onClick={onMobileClose}
                      title={visuallyCollapsed ? item.label : undefined}
                    >
                      {active && <span className="admin-sidebar__active-rail" />}
                      <Icon aria-hidden="true" size={16} />
                      {!visuallyCollapsed && <span>{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="admin-sidebar__footer">
          <Link
            aria-label={visuallyCollapsed ? "Back to knowledge workspace" : undefined}
            className={cn(
              "admin-sidebar__item",
              visuallyCollapsed && "admin-sidebar__item--collapsed",
            )}
            href="/app"
            title={visuallyCollapsed ? "Back to knowledge workspace" : undefined}
          >
            <MessageSquareText aria-hidden="true" size={16} />
            {!visuallyCollapsed && <span>Knowledge workspace</span>}
          </Link>
        </div>
      </aside>
    </>
  );
}

export function MobileMenuButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      aria-label="Open admin navigation"
      className="admin-topbar__menu"
      onClick={onClick}
      type="button"
    >
      <Menu aria-hidden="true" size={17} />
    </button>
  );
}
