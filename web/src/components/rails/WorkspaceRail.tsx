"use client";

import { usePathname } from "next/navigation";

import { ContextHeader, NavItem } from "@/components/patterns";
import { useAuthPrompt } from "@/components/auth/AuthPrompt";
import { isGuestSession } from "@/lib/auth/session";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { isRailItemActive, workspaceRailItems } from "@/lib/navigation";

import { Rail, RailDivider, RailGroup, RailScroll, RailSpacer } from "./Rail";
import { WorkspaceContextMenu } from "./WorkspaceContextMenu";

/**
 * Mode 1 — the User Workspace rail.
 *
 * Deliberately light: three intents, recents, and one dock-owned context menu.
 * No tenant settings, roles, connectors or system configuration appear in the
 * navigation itself; allowed context actions live only in the bottom dock.
 */
export function WorkspaceRail({
  collapsed,
  mobileOpen,
  onMobileClose,
  onToggleCollapse,
  children,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  onToggleCollapse?: () => void;
  /** Recent conversations, contributed by Chat. */
  children?: React.ReactNode;
}) {
  const pathname = usePathname();
  const { requestSignIn } = useAuthPrompt();
  const session = useAuthSession();
  const activeWorkspace = session?.tenants.find((item) => item.id === session.active_tenant_id);

  return (
    <Rail ariaLabel="Workspace" collapsed={collapsed} mobileOpen={mobileOpen} onMobileClose={onMobileClose} onToggleCollapse={onToggleCollapse}>
      <RailGroup>
        <ContextHeader
          collapsed={collapsed}
          context="Workspace"
          name={activeWorkspace?.name ?? "BoThesis"}
        />
      </RailGroup>

      <RailGroup className="pt-1">
        {workspaceRailItems.map((item) => (
          <NavItem
            active={isRailItemActive(item, pathname)}
            collapsed={collapsed}
            href={isGuestSession(session) && item.id === "library" ? undefined : item.href}
            icon={item.icon}
            key={item.id}
            label={item.label}
            onClick={() => {
              onMobileClose();
              if (isGuestSession(session) && item.id === "library") {
                requestSignIn("Sign in to upload and keep private files.");
              }
            }}
          />
        ))}
      </RailGroup>

      {children && (
        <>
          <RailDivider />
          <RailScroll>{children}</RailScroll>
        </>
      )}

      {!children && <RailSpacer />}
      <RailDivider />
      <RailGroup className="pb-0">
        <WorkspaceContextMenu collapsed={collapsed} onNavigate={onMobileClose} />
      </RailGroup>
    </Rail>
  );
}
