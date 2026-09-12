"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getAuthSession,
  hasAnySessionPermission,
  type AuthSession,
} from "@/lib/auth/session";
import {
  isProductNavigationActive,
  productNavigationActions,
  productNavigationItems,
} from "@/lib/product-navigation";
import { cn } from "@/lib/cn";

interface ProductSidebarGlobalNavigationProps {
  collapsed?: boolean;
  onNavigate?: () => void;
  onNewChat?: () => void;
  onSearchChats?: () => void;
}

/**
 * The first navigation tier for every product surface. Context links belong
 * below this component; they must not redefine product destinations.
 */
export function ProductSidebarGlobalNavigation({
  collapsed = false,
  onNavigate,
  onNewChat,
  onSearchChats,
}: ProductSidebarGlobalNavigationProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [session, setSession] = useState<AuthSession | null>(null);

  useEffect(() => setSession(getAuthSession()), []);

  return (
    <nav aria-label="Product" className="product-global-nav">
      <div className="product-global-nav__actions">
        {productNavigationActions.map((action) => {
          const Icon = action.icon;
          const onAction = action.id === "new-chat" ? onNewChat : onSearchChats;
          if (onAction) {
            return (
              <button className="product-global-nav__action" key={action.id} onClick={() => { onAction(); onNavigate?.(); }} title={collapsed ? action.label : undefined} type="button">
                <Icon aria-hidden="true" className="product-global-nav__icon" size={16} />
                {!collapsed && <span className="product-global-nav__label">{action.label}</span>}
              </button>
            );
          }
          return (
            <Link className="product-global-nav__action" href={action.href} key={action.id} onClick={onNavigate} title={collapsed ? action.label : undefined}>
              <Icon aria-hidden="true" className="product-global-nav__icon" size={16} />
              {!collapsed && <span className="product-global-nav__label">{action.label}</span>}
            </Link>
          );
        })}
      </div>
      <div className="product-global-nav__destinations">
        {productNavigationItems
          .filter((item) => !item.permissionCodes || hasAnySessionPermission(session, item.permissionCodes))
          .map((item) => {
            const Icon = item.icon;
            const active = isProductNavigationActive(pathname, item.href, searchParams.toString());
            return (
              <Link aria-current={active ? "page" : undefined} className={cn("product-global-nav__item", active && "is-active")} href={item.href} key={item.id} onClick={onNavigate} title={collapsed ? item.label : undefined}>
                <Icon aria-hidden="true" className="product-global-nav__icon" size={18} />
                {!collapsed && <span className="product-global-nav__label">{item.label}</span>}
              </Link>
            );
          })}
      </div>
    </nav>
  );
}
