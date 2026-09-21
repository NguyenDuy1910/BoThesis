"use client";

import { LogIn, LogOut, Settings, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Dropdown, DropdownItem, DropdownSeparator } from "@/components/ui/Dropdown";
import { useAuthPrompt } from "@/components/auth/AuthPrompt";
import {
  clearAuthSession,
  hasAnySessionPermission,
  canAccessPlatformControl,
  isGuestSession,
} from "@/lib/auth/session";
import { switchWorkspace } from "@/modules/auth/api";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

import { AccountDialog } from "./AccountDialog";
import { IdentityContextDock } from "./IdentityContextDock";
import { WorkspaceSwitcherDialog } from "./WorkspaceSwitcherDialog";

const workspaceControlPermissions = [
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
 * workspace rail that can change workspaces or cross into platform control.
 */
export function WorkspaceContextMenu({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const router = useRouter();
  const { requestSignIn } = useAuthPrompt();
  const [open, setOpen] = useState(false);
  const [accountTab, setAccountTab] = useState<"profile" | "preferences">("profile");
  const [accountOpen, setAccountOpen] = useState(false);
  const [workspaceSwitcherOpen, setWorkspaceSwitcherOpen] = useState(false);
  const session = useAuthSession();
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const current = session?.workspaces.find((tenant) => tenant.id === session.active_workspace_id);
  const workspaceName = current?.name ?? "Workspace";
  const userName = isGuestSession(session)
    ? "Guest session"
    : session?.display_name || session?.email || "Signed in";
  const otherWorkspaces = (session?.workspaces ?? []).filter((tenant) => tenant.id !== current?.id);
  const canManageWorkspace = hasAnySessionPermission(session, workspaceControlPermissions);
  const canUsePlatformControl = canAccessPlatformControl(session);
  const isGuest = isGuestSession(session);

  const changeWorkspace = async (tenantId: string) => {
    if (!session || tenantId === session.active_workspace_id) return;
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
    router.replace("/app");
    router.refresh();
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
            router.push("/workspace-control");
          }}
        >
          <Settings aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Manage workspace</span>
        </DropdownItem>
      )}

      {canUsePlatformControl && (
        <DropdownItem
          onClick={() => {
            onNavigate?.();
            router.push("/workspace-control/platform");
          }}
        >
          <ShieldCheck aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Platform control</span>
        </DropdownItem>
      )}

      {isGuest && (
        <DropdownItem onClick={() => requestSignIn("Sign in to keep this conversation and unlock your workspace.")}>
          <LogIn aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Sign in</span>
        </DropdownItem>
      )}

      {session && !isGuest && (otherWorkspaces.length > 0 || canManageWorkspace || canUsePlatformControl) && <DropdownSeparator />}

      {session && !isGuest && (
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

      {session && !isGuest && (
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
        workspaces={session?.workspaces ?? []}
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
