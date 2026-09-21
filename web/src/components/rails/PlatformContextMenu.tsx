"use client";

import { ArrowLeft, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Dropdown, DropdownItem, DropdownSeparator } from "@/components/ui/Dropdown";
import { clearAuthSession } from "@/lib/auth/session";
import { switchWorkspace } from "@/modules/auth/api";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

import { AccountDialog } from "./AccountDialog";
import { IdentityContextDock } from "./IdentityContextDock";
import { WorkspaceSwitcherDialog } from "./WorkspaceSwitcherDialog";

/** The platform dock menu keeps the route back to the active workspace local. */
export function PlatformContextMenu({
  collapsed,
  onNavigate,
  platformContext,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
  platformContext: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [accountTab, setAccountTab] = useState<"profile" | "preferences">("profile");
  const [accountOpen, setAccountOpen] = useState(false);
  const [workspaceSwitcherOpen, setWorkspaceSwitcherOpen] = useState(false);
  const session = useAuthSession();
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const userName = session?.display_name || session?.email || "Signed in";
  const current = session?.workspaces.find((workspace) => workspace.id === session.active_workspace_id);
  const otherWorkspaces = (session?.workspaces ?? []).filter((workspace) => workspace.id !== current?.id);

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
    router.replace("/auth/login");
  };

  return (
    <>
      <Dropdown
      align="left"
      ariaLabel="Platform account"
      buttonClassName={dockTriggerClass(collapsed, open)}
      className="w-full"
      closeOnScroll={false}
      label={
        <IdentityContextDock
          collapsed={collapsed}
          open={open}
          platformContext={platformContext}
          userName={userName}
          variant="platform"
        />
      }
      menuClassName="w-[17.75rem] border border-[var(--border-subtle)] p-2"
      onOpenChange={setOpen}
      open={open}
      showChevron={false}
      title={`${userName} — ${platformContext}`}
    >
      <DropdownItem
        onClick={() => {
          onNavigate?.();
          router.push("/app");
        }}
      >
        <ArrowLeft aria-hidden="true" className="h-[18px] w-[18px]" />
        <span className="flex-1">Back to workspace</span>
      </DropdownItem>

      {otherWorkspaces.length > 0 && (
        <>
          <DropdownSeparator />
          <DropdownItem onClick={() => setWorkspaceSwitcherOpen(true)}>
            <span className="flex-1">Switch workspace</span>
          </DropdownItem>
        </>
      )}

      {session && <DropdownSeparator />}
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
        workspaces={session?.workspaces ?? []}
      />
    </>
  );
}

function dockTriggerClass(collapsed: boolean, open: boolean) {
  return [
    "w-full min-w-0 cursor-pointer rounded-[var(--radius-sm)] bg-transparent px-2 shadow-none",
    "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)] hover:bg-[var(--surface-hover)] hover:shadow-none",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-inset)]",
    collapsed ? "h-10 justify-center px-0" : "h-[60px] justify-start",
    open ? "bg-[var(--surface-selected)] text-[var(--text-primary)]" : "text-[var(--text-secondary)]",
  ].join(" ");
}
