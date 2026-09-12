"use client";

import { ChevronRight, Menu, PanelLeftOpen, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { appBrand } from "@/lib/brand";
import { adminRoutes } from "@/modules/admin/navigation";

interface Crumb {
  label: string;
  href?: string;
}

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Breadcrumbs are built from the same route registry the sidebar uses, so the
 * trail always reads with the same words as the navigation item that led here.
 */
function buildCrumbs(pathname: string, detailTitle?: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "admin") return [];
  const rest = segments.slice(1);
  if (!rest.length) return [{ label: "Dashboard" }];

  const route = adminRoutes.find((entry) => entry.path === `/admin/${rest[0]}`);
  const crumbs: Crumb[] = [{ label: "Dashboard", href: "/admin" }];
  crumbs.push({
    label: route?.label ?? rest[0].replace(/[-_]/g, " "),
    href: rest.length > 1 ? (route?.path ?? `/admin/${rest[0]}`) : undefined,
  });

  if (rest.length > 1) {
    const tail = rest[rest.length - 1];
    crumbs.push({
      label: detailTitle ?? (uuidPattern.test(tail) ? "Details" : tail.replace(/[-_]/g, " ")),
    });
  }
  return crumbs;
}

interface AdminTopbarProps {
  onMobileMenuOpen: () => void;
  onSearchOpen: () => void;
  collapsed: boolean;
  onExpand: () => void;
  /** Name of the record on a detail page, so the trail ends in something real. */
  detailTitle?: string;
  actions?: React.ReactNode;
}

export function AdminTopbar({
  onMobileMenuOpen,
  onSearchOpen,
  collapsed,
  onExpand,
  detailTitle,
  actions,
}: AdminTopbarProps) {
  const pathname = usePathname();
  const crumbs = buildCrumbs(pathname, detailTitle);

  return (
    <header className="adm-top">
      <Button
        aria-label="Open navigation"
        className="md:hidden"
        icon={<Menu aria-hidden="true" className="h-4 w-4" />}
        iconOnly
        onClick={onMobileMenuOpen}
        size="sm"
        variant="ghost"
      />
      {collapsed && (
        <Tooltip label="Expand navigation">
          <Button
            aria-label="Expand navigation"
            className="hidden md:inline-flex"
            icon={<PanelLeftOpen aria-hidden="true" className="h-4 w-4" />}
            iconOnly
            onClick={onExpand}
            size="sm"
            variant="ghost"
          />
        </Tooltip>
      )}

      <nav aria-label="Breadcrumb" className="adm-top__crumbs">
        {crumbs.map((crumb, index) => (
          <span className="flex min-w-0 items-center gap-1" key={`${crumb.label}-${index}`}>
            {index > 0 && <ChevronRight aria-hidden="true" size={13} />}
            {crumb.href ? (
              <Link href={crumb.href}>{crumb.label}</Link>
            ) : (
              <span aria-current="page">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>

      <div className="adm-top__actions">
        <button
          aria-label={`Search ${appBrand.productName} Admin`}
          className="adm-search"
          onClick={onSearchOpen}
          type="button"
        >
          <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
          <span>Search…</span>
          <kbd className="adm-kbd">⌘K</kbd>
        </button>
        {actions}
      </div>
    </header>
  );
}
