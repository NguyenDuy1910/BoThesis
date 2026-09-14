"use client";

import { usePathname } from "next/navigation";

import { ContextHeader, NavItem } from "@/components/patterns";
import { hasAnySessionPermission } from "@/lib/auth/session";
import {
  isRailItemActive,
  visibleRailItems,
  workspaceAdminRailItems,
  workspaceAdminRailTail,
} from "@/lib/navigation";
import { useAdminWorkspace } from "@/modules/admin/workspace";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

import { Rail, RailDivider, RailGroup, RailScroll } from "./Rail";
import { WorkspaceContextMenu } from "./WorkspaceContextMenu";

/**
 * Mode 2 — the Workspace Admin rail.
 *
 * Administration of the currently selected tenant. The chat rail is never
 * shown here; the context header states where you are and is the explicit way
 * back. Settings remains part of the navigation system; the dock only owns
 * identity and context actions.
 */
export function WorkspaceAdminRail({
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
  const { tenant } = useAdminWorkspace();
  const session = useAuthSession();

  const sessionTenant = session?.tenants.find((item) => item.id === session.active_tenant_id);
  const name = tenant?.name ?? sessionTenant?.name ?? "This workspace";
  const can = (codes: readonly string[]) => hasAnySessionPermission(session, codes);
  const items = visibleRailItems(workspaceAdminRailItems, can);
  const tail = visibleRailItems(workspaceAdminRailTail, can);

  return (
    <Rail ariaLabel="Workspace admin" collapsed={collapsed} mobileOpen={mobileOpen} onMobileClose={onMobileClose} onToggleCollapse={onToggleCollapse}>
      <RailGroup>
        <ContextHeader
          collapsed={collapsed}
          context="Workspace admin"
          name={name}
          onNavigate={onMobileClose}
        />
      </RailGroup>
      <RailDivider />

      <RailScroll>
        <RailGroup>
          {items.map((item) => (
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
        {tail.length > 0 && (
          <>
            <RailDivider />
            <RailGroup>
              {tail.map((item) => (
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
          </>
        )}
      </RailScroll>

      <RailDivider />
      <RailGroup>
        <WorkspaceContextMenu collapsed={collapsed} onNavigate={onMobileClose} />
      </RailGroup>
    </Rail>
  );
}
