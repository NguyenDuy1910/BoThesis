"use client";

import { usePathname } from "next/navigation";

import { ContextHeader, NavItem } from "@/components/patterns";
import { appBrand } from "@/lib/brand";
import { isRailItemActive, platformAdminRailItems } from "@/lib/navigation";

import { Rail, RailDivider, RailGroup, RailScroll } from "./Rail";
import { PlatformContextMenu } from "./PlatformContextMenu";

/**
 * Mode 3 — the Platform Admin rail.
 *
 * A separate control plane for Root Admin. It names BoThesis rather than a
 * workspace and sits on a different surface, so it can never be mistaken for
 * Workspace Admin. This is the only rail that speaks in tenants.
 */
export function PlatformAdminRail({
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
      ariaLabel="Platform admin"
      collapsed={collapsed}
      mobileOpen={mobileOpen}
      onMobileClose={onMobileClose}
      onToggleCollapse={onToggleCollapse}
      surface="inset"
    >
      <RailGroup>
        <ContextHeader
          collapsed={collapsed}
          context="Platform admin"
          name={appBrand.platformName}
          onNavigate={onMobileClose}
        />
      </RailGroup>
      <RailDivider />

      <RailScroll>
        <RailGroup>
          {platformAdminRailItems.map((item) => (
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
          platformContext="Platform Admin"
        />
      </RailGroup>
    </Rail>
  );
}
