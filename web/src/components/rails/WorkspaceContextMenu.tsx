"use client";

import { LogOut, Settings, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Dropdown, DropdownItem, DropdownSeparator } from "@/components/ui/Dropdown";
import {
  clearAuthSession,
  hasAnySessionPermission,
  canAccessPlatformAdmin,
} from "@/lib/auth/session";
import { switchWorkspace } from "@/modules/auth/api";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

import { AccountDialog } from "./AccountDialog";
import { IdentityContextDock } from "./IdentityContextDock";
import { WorkspaceSwitcherDialog } from "./WorkspaceSwitcherDialog";

const workspaceAdminPermissions = [
  "admin",
  "user.manage",
  "role.manage",
  "group.manage",
  "access.manage",
  "audit.read",
  "tenant.manage",
] as const;

/**
 * The workspace dock's compact context menu. It is the only control in either
 * workspace rail that can change workspaces or cross into platform admin.
 */
export function WorkspaceContextMenu({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [accountTab, setAccountTab] = useState<"profile" | "preferences">("profile");
  const [accountOpen, setAccountOpen] = useState(false);
  const [workspaceSwitcherOpen, setWorkspaceSwitcherOpen] = useState(false);
  const session = useAuthSession();
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = session?.tenants.find((tenant) => tenant.id === session.active_tenant_id);
  const workspaceName = current?.name ?? "Workspace";
  const userName = session?.display_name || session?.email || "Signed in";
  const otherWorkspaces = (session?.tenants ?? []).filter((tenant) => tenant.id !== current?.id);
  const canManageWorkspace = hasAnySessionPermission(session, workspaceAdminPermissions);
  const canUsePlatformAdmin = canAccessPlatformAdmin(session);

  const changeWorkspace = async (tenantId: string) => {
    if (!session || tenantId === session.active_tenant_id) return;
    setSwitching(tenantId);
    setError(null);
    try {
      await switchWorkspace(tenantId);
      setWorkspaceSwitcherOpen(false);
      setSwitching(null);
      router.push("/app?action=new");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not change workspace.");
      setSwitching(null);
    }
  };

  const signOut = () => {
    clearAuthSession();
    router.replace("/auth/login");
  };

  return (
    <>
      <Dropdown
      align="left"
      ariaLabel="Workspace and account"
      buttonClassName={dockTriggerClass(collapsed, open)}
      className="w-full"
      closeOnScroll={false}
      label={
        <IdentityContextDock
          collapsed={collapsed}
          open={open}
          userName={userName}
          variant="workspace"
          workspaceName={workspaceName}
        />
      }
      menuClassName="w-[17.75rem] border border-[var(--border-subtle)] p-2"
      onOpenChange={setOpen}
      open={open}
      showChevron={false}
      title={`${workspaceName} — ${userName}`}
    >
      {otherWorkspaces.length > 0 && (
        <DropdownItem onClick={() => setWorkspaceSwitcherOpen(true)}>
          <span className="flex-1">Switch workspace</span>
        </DropdownItem>
      )}

      {canManageWorkspace && (
        <DropdownItem
          onClick={() => {
            onNavigate?.();
            router.push("/admin");
          }}
        >
          <Settings aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Manage workspace</span>
        </DropdownItem>
      )}

      {canUsePlatformAdmin && (
        <DropdownItem
          onClick={() => {
            onNavigate?.();
            router.push("/admin/platform");
          }}
        >
          <ShieldCheck aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Platform admin</span>
        </DropdownItem>
      )}

      {session && (otherWorkspaces.length > 0 || canManageWorkspace || canUsePlatformAdmin) && <DropdownSeparator />}

      {session && (
        <>
          <DropdownItem
            onClick={() => {
              onNavigate?.();
              setAccountTab("profile");
              setAccountOpen(true);
            }}
          >
            <span className="flex-1">Profile</span>
          </DropdownItem>
          <DropdownItem
            onClick={() => {
              onNavigate?.();
              setAccountTab("preferences");
              setAccountOpen(true);
            }}
          >
            <span className="flex-1">Preferences</span>
          </DropdownItem>
        </>
      )}

      {session && (
        <>
          <DropdownSeparator />
          <DropdownItem destructive onClick={signOut}>
            <LogOut aria-hidden="true" className="h-[18px] w-[18px]" />
            <span className="flex-1">Sign out</span>
          </DropdownItem>
        </>
      )}

      {error && (
        <p className="px-2.5 py-1.5 text-[length:var(--text-size-meta)] text-[var(--status-danger-text)]" role="alert">
          {error}
        </p>
      )}
      </Dropdown>
      <AccountDialog initialTab={accountTab} onClose={() => setAccountOpen(false)} open={accountOpen} session={session} />
      <WorkspaceSwitcherDialog
        error={error}
        onClose={() => setWorkspaceSwitcherOpen(false)}
        onSelect={(tenantId) => void changeWorkspace(tenantId)}
        open={workspaceSwitcherOpen}
        switchingId={switching}
        workspaces={session?.tenants ?? []}
      />
    </>
  );
}

function dockTriggerClass(collapsed: boolean, open: boolean) {
  return [
    "w-full min-w-0 cursor-pointer rounded-[var(--radius-sm)] bg-transparent px-2 shadow-none",
    "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)] hover:bg-[var(--surface-hover)] hover:shadow-none",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-nav)]",
    collapsed ? "h-10 justify-center px-0" : "h-14 justify-start",
    open ? "bg-[var(--surface-selected)] text-[var(--text-primary)]" : "text-[var(--text-secondary)]",
  ].join(" ");
}
