"use client";

import { ChevronRight, Menu, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";
import { modeForPath } from "@/lib/navigation";
import { adminNavGroupLabels, routeForPath } from "@/modules/admin/navigation";

interface Crumb {
  label: string;
  href?: string;
}

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Breadcrumbs are built from the same route registry the sidebar uses, so the
 * trail always reads with the same words as the navigation item that led here.
 *
 * A trail only earns the strip when there is somewhere to walk back to. On a
 * section's own page there is not: the rail states the mode in its context
 * header and marks the destination as selected, so "Workspace admin ›
 * Knowledge" above a page the rail already labels Knowledge spends the widest
 * band of the window restating what the reader can see. Detail pages keep the
 * trail, because the way back to the section is genuinely not on screen.
 */
function buildCrumbs(pathname: string, detailTitle?: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "admin") return [];

  const route = routeForPath(pathname);
  if (!route || pathname === route.path) return [];

  // The trail must name the mode it is actually in. Labelling a platform
  // address "Workspace" tells a root admin they are somewhere they are not.
  const platform = modeForPath(pathname) === "platform-admin";
  const root: Crumb = platform
    ? { label: adminNavGroupLabels.platform, href: "/admin/platform" }
    : { label: adminNavGroupLabels.workspace, href: "/admin" };

  const tail = segments[segments.length - 1];
  return [
    root,
    { label: route.label, href: route.path },
    { label: detailTitle ?? (uuidPattern.test(tail) ? "Details" : tail.replace(/[-_]/g, " ")) },
  ];
}

interface AdminTopbarProps {
  onMobileMenuOpen: () => void;
  collapsed: boolean;
  onExpand: () => void;
  /** Name of the record on a detail page, so the trail ends in something real. */
  detailTitle?: string;
  actions?: React.ReactNode;
}

/**
 * The strip above the working area.
 *
 * It carries only what the rail cannot: the control that opens the rail when
 * it is an overlay, the one that expands it when it is collapsed, a trail on
 * a detail page, and whatever the page itself puts there. When none of those
 * apply — a section page on a wide window with the rail open — there is
 * nothing left to carry, and the strip takes no height at all rather than
 * spending a band of the window on a border.
 */
export function AdminTopbar({
  onMobileMenuOpen,
  collapsed,
  onExpand,
  detailTitle,
  actions,
}: AdminTopbarProps) {
  const pathname = usePathname();
  const crumbs = buildCrumbs(pathname, detailTitle);
  // The mobile menu button is the one piece that appears by width alone, so
  // "empty" is decided in CSS rather than here.
  const bare = crumbs.length === 0 && !collapsed && !actions;

  return (
    <header className={cn("adm-top", bare && "adm-top--bare")}>
      <Button
        aria-label="Open navigation"
        className="lg:hidden"
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
            className="hidden lg:inline-flex"
            icon={<PanelLeftOpen aria-hidden="true" className="h-4 w-4" />}
            iconOnly
            onClick={onExpand}
            size="sm"
            variant="ghost"
          />
        </Tooltip>
      )}

      {crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="adm-top__crumbs">
          {crumbs.map((crumb, index) => (
            <span className="flex min-w-0 items-center gap-1" key={`${crumb.label}-${index}`}>
              {index > 0 && <ChevronRight aria-hidden="true" size={14} />}
              {crumb.href ? (
                <Link href={crumb.href}>{crumb.label}</Link>
              ) : (
                <span aria-current="page">{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}

      {actions && <div className="adm-top__actions">{actions}</div>}
    </header>
  );
}
