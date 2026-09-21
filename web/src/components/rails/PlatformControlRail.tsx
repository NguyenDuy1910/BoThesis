"use client";

import { usePathname } from "next/navigation";

import { ContextHeader, NavItem } from "@/components/patterns";
import { appBrand } from "@/lib/brand";
import { isRailItemActive, platformControlRailItems } from "@/lib/navigation";

import { Rail, RailDivider, RailGroup, RailScroll } from "./Rail";
import { PlatformContextMenu } from "./PlatformContextMenu";

/**
 * Mode 3 — the Platform control rail.
 *
 * A separate control plane for platform operators. It names BoThesis rather than a
 * workspace and sits on a different surface, so it can never be mistaken for
 * Workspace control. This is the only rail that speaks in tenants.
 */
export function PlatformControlRail({
  collapsed,
  mobileOpen,
  onMobileClose,
  onToggleCollapse,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  onToggleCollapse?: () => void;
}) {
  const pathname = usePathname();

  return (
    <Rail
      ariaLabel="Platform control"
      collapsed={collapsed}
      mobileOpen={mobileOpen}
      onMobileClose={onMobileClose}
      onToggleCollapse={onToggleCollapse}
      surface="inset"
    >
      <RailGroup>
        <ContextHeader
          collapsed={collapsed}
          context="Platform control"
          name={appBrand.platformName}
          onNavigate={onMobileClose}
        />
      </RailGroup>
      <RailDivider />

      <RailScroll>
        <RailGroup>
          {platformControlRailItems.map((item) => (
            <NavItem
              active={isRailItemActive(item, pathname)}
              collapsed={collapsed}
              href={item.href}
              icon={item.icon}
              key={item.id}
              label={item.label}
              onClick={onMobileClose}
            />
          ))}
        </RailGroup>
      </RailScroll>

      <RailDivider />
      <RailGroup>
        <PlatformContextMenu
          collapsed={collapsed}
          onNavigate={onMobileClose}
          platformContext="Platform control"
        />
      </RailGroup>
    </Rail>
  );
}
