"use client";

import {
  Check,
  ChevronRight,
  LogIn,
  LogOut,
  SlidersHorizontal,
  Settings,
  ShieldCheck,
  UserRound,
  UsersRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Dropdown, DropdownItem, DropdownSeparator } from "@/components/ui/Dropdown";
import { useAuthPrompt } from "@/components/auth/AuthPrompt";
import { WorkspaceMark } from "@/components/patterns";
import { Avatar } from "@/components/ui/Avatar";
import {
  clearAuthSession,
  hasAnySessionPermission,
  canAccessPlatformControl,
  isGuestSession,
} from "@/lib/auth/session";
import { useWorkspaceSwitch } from "@/modules/auth/queries";
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
  const { error, switchingId: switching, switchWorkspace: selectWorkspace } = useWorkspaceSwitch();

  const current = session?.workspaces.find((tenant) => tenant.id === session.active_workspace_id);
  const workspaceName = current?.name ?? "Workspace";
  const userName = isGuestSession(session)
    ? "Guest session"
    : session?.display_name || session?.email || "Signed in";
  const otherWorkspaces = (session?.workspaces ?? []).filter((tenant) => tenant.id !== current?.id);
  const canManageWorkspace = hasAnySessionPermission(session, workspaceControlPermissions);
  const canUsePlatformControl = canAccessPlatformControl(session);
  const isGuest = isGuestSession(session);

  const changeWorkspace = async (workspaceId: string) => {
    if (await selectWorkspace(workspaceId)) {
      setWorkspaceSwitcherOpen(false);
      setOpen(false);
      onNavigate?.();
      router.replace("/app?action=new");
    }
  };

  const signOut = () => {
    clearAuthSession();
    router.replace("/app");
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
      menuClassName="w-[26rem] max-w-[calc(100vw-1rem)] border border-[var(--border-subtle)] p-2"
      onOpenChange={setOpen}
      open={open}
      showChevron={false}
      title={`${workspaceName} — ${userName}`}
    >
      <div className="px-2.5 pb-2 pt-1" role="presentation">
        <p className="truncate text-[length:var(--text-size-meta)] text-[var(--text-secondary)]">
          {session?.email ?? (isGuest ? "Guest session" : "Signed in")}
        </p>
        <div className="mt-2 flex items-center gap-3">
          <Avatar name={userName} size="lg" />
          <div className="min-w-0">
            <p className="truncate text-[length:var(--text-size-body)] font-semibold text-[var(--text-primary)]">
              {userName}
            </p>
            <p className="text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
              {isGuest ? "Guest session" : "Member"}
            </p>
          </div>
        </div>
      </div>

      {session && !isGuest && <DropdownSeparator />}
      {session && !isGuest && (
        <div className="px-2.5 pb-1 pt-2 text-[length:var(--text-size-meta)] font-medium text-[var(--text-tertiary)]" role="presentation">
          Switch workspace
        </div>
      )}

      {current && (
        <DropdownItem
          aria-current="true"
          className="min-h-12 py-2"
          disabled={Boolean(switching)}
          selected
          onClick={() => undefined}
        >
          <WorkspaceMark name={current.name} size="md" />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{current.name}</span>
            <span className="block text-[length:var(--text-size-meta)] font-normal text-[var(--text-tertiary)]">Current workspace</span>
          </span>
          <Check aria-hidden="true" className="h-4 w-4" />
        </DropdownItem>
      )}

      {otherWorkspaces.slice(0, 1).map((workspace) => (
        <DropdownItem
          className="min-h-12 py-2"
          disabled={Boolean(switching)}
          key={workspace.id}
          onClick={() => void changeWorkspace(workspace.id)}
        >
          <WorkspaceMark name={workspace.name} size="md" />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{workspace.name}</span>
            <span className="block text-[length:var(--text-size-meta)] font-normal text-[var(--text-tertiary)]">
              {switching === workspace.id ? "Switching…" : "Available workspace"}
            </span>
          </span>
        </DropdownItem>
      ))}

      {otherWorkspaces.length > 1 && (
        <DropdownItem onClick={() => setWorkspaceSwitcherOpen(true)}>
          <UsersRound aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">View all workspaces</span>
          <ChevronRight aria-hidden="true" className="h-4 w-4 text-[var(--text-tertiary)]" />
        </DropdownItem>
      )}

      {(canManageWorkspace || canUsePlatformControl) && (
        <>
          <DropdownSeparator />
          <div className="px-2.5 pb-1 pt-2 text-[length:var(--text-size-meta)] font-medium text-[var(--text-tertiary)]" role="presentation">
            Workspace &amp; platform
          </div>
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
        </>
      )}

      {isGuest && (
        <DropdownItem onClick={() => requestSignIn("Sign in to keep this conversation and unlock your workspace.")}>
          <LogIn aria-hidden="true" className="h-[18px] w-[18px]" />
          <span className="flex-1">Sign in</span>
        </DropdownItem>
      )}

      {session && !isGuest && (
        <>
          <DropdownSeparator />
          <div className="px-2.5 pb-1 pt-2 text-[length:var(--text-size-meta)] font-medium text-[var(--text-tertiary)]" role="presentation">
            Personal
          </div>
          <DropdownItem
            className="min-h-10"
            onClick={() => {
              onNavigate?.();
              setAccountTab("profile");
              setAccountOpen(true);
            }}
          >
            <UserRound aria-hidden="true" className="h-[18px] w-[18px]" />
            <span className="flex-1">Profile</span>
          </DropdownItem>
          <DropdownItem
            className="min-h-10"
            onClick={() => {
              onNavigate?.();
              setAccountTab("preferences");
              setAccountOpen(true);
            }}
          >
            <SlidersHorizontal aria-hidden="true" className="h-[18px] w-[18px]" />
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
