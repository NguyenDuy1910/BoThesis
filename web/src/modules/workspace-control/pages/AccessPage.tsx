"use client";

import { Plus, ShieldCheck, UserPlus, Users, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";

import { FilterTrigger, CommandBar } from "@/components/layout/CommandBar";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import {
  workspaceDirectoryApi,
  memberName,
  memberStatus,
  roleNames,
  type Group,
  type Member,
  type Permission,
  type Role,
} from "@/modules/workspace-control/directory";
import { useControlPlaneData } from "@/modules/workspace-control/queries";
import { Skeleton, TableSkeleton } from "@/components/ui/Skeleton";

type AccessTab = "members" | "groups" | "roles";

const tabs = [
  { id: "members", label: "Members" },
  { id: "groups", label: "Groups" },
  { id: "roles", label: "Roles" },
];

export function AccessPage() {
  const [routeTab, setRouteTab] = useRouteState("tab", "members");
  const session = useAuthSession();
  const tab = tabs.some((item) => item.id === routeTab) ? (routeTab as AccessTab) : "members";

  return (
    <>
      <Tabs activeTab={tab} ariaLabel="Access sections" className="mb-4" onChange={setRouteTab} tabs={tabs} />
      {tab === "members" && <MembersSection actorUserId={session?.user_id ?? null} />}
      {tab === "groups" && <GroupsSection />}
      {tab === "roles" && <RolesSection />}
    </>
  );
}

function MembersSection({ actorUserId }: { actorUserId: string | null }) {
  const members = useControlPlaneData(() => workspaceDirectoryApi.members());
  const roles = useControlPlaneData(() => workspaceDirectoryApi.roles());
  const error = members.error || roles.error;

  if (error) {
    return <ErrorState description={error} layout="inline" onAction={() => { members.reload(); roles.reload(); }} />;
  }
  if (!members.data || !roles.data) return <AccessDataLoading />;
  return <MembersPanel actorUserId={actorUserId} roles={roles.data.items} rows={members.data.items} />;
}

function GroupsSection() {
  const groups = useControlPlaneData(() => workspaceDirectoryApi.groups());

  if (groups.error) return <ErrorState description={groups.error} layout="inline" onAction={groups.reload} />;
  if (!groups.data) return <AccessDataLoading columns={3} />;
  return <GroupsPanel rows={groups.data.items} />;
}

function RolesSection() {
  const roles = useControlPlaneData(() => workspaceDirectoryApi.roles());

  if (roles.error) return <ErrorState description={roles.error} layout="inline" onAction={roles.reload} />;
  if (!roles.data) return <AccessDataLoading />;
  return <RolesPanel rows={roles.data.items} />;
}

function AccessDataLoading({ columns = 4 }: { columns?: number }) {
  return (
    <section aria-busy="true" aria-label="Loading access records" role="status">
      <span className="sr-only">Loading access records</span>
      <div className="ctl-card overflow-hidden">
        <TableSkeleton columns={columns} rows={6} />
      </div>
    </section>
  );
}

function MembersPanel({
  actorUserId,
  rows,
  roles,
}: {
  actorUserId: string | null;
  rows: Member[];
  roles: Role[];
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Member | null>(null);
  const matching = useMemo(() => rows.filter((row) => {
    const term = search.toLowerCase();
    return (!term || `${memberName(row)} ${row.email} ${roleNames(row)}`.toLowerCase().includes(term))
      && (!status || memberStatus(row) === status);
  }), [rows, search, status]);

  const columns: Column<Member>[] = [
    {
      key: "email",
      label: "Member",
      primary: true,
      sortable: true,
      render: (row) => (
        <CellTitle icon={<Avatar name={memberName(row)} size="md" />} subtitle={row.email} title={memberName(row)} />
      ),
    },
    { key: "membership", label: "Workspace roles", priority: "medium", render: (row) => roleNames(row) || "No role" },
    {
      key: "groups",
      label: "Groups",
      priority: "low",
      render: (row) => row.groups.map((group) => group.display_name).join(", ") || "Direct access only",
    },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={memberStatus(row)} /> },
  ];

  return <>
    <CommandBar
      action={<Button icon={<UserPlus size={16} />} onClick={() => setOpen(true)}>Add member</Button>}
      count={`${matching.length} members`}
      filters={
        <FilterTrigger
          label="Filter by status"
          onChange={setStatus}
          options={[
            { value: "", label: "All statuses" },
            { value: "active", label: "Active" },
            { value: "suspended", label: "Suspended" },
          ]}
          value={status}
        />
      }
      search={{ value: search, onChange: setSearch, placeholder: "Search members…", label: "Search members" }}
    />
    <DataTable
      ariaLabel="Workspace members"
      columns={columns}
      data={matching}
      emptyState={<EmptyState description="Clear the filters or add a member." icon={<Users size={20} />} title="No matching members" />}
      onRowClick={setSelected}
    />
    <MemberDialog
      actorUserId={actorUserId}
      member={selected}
      onClose={() => setSelected(null)}
      roles={roles}
    />
    <AddMemberDialog onClose={() => setOpen(false)} open={open} roles={roles} />
  </>;
}

function MemberDialog({
  actorUserId,
  member,
  roles,
  onClose,
}: {
  actorUserId: string | null;
  member: Member | null;
  roles: Role[];
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingRoleId, setPendingRoleId] = useState<string | null>(null);
  const [confirmStatusChange, setConfirmStatusChange] = useState(false);
  if (!member) return null;
  const active = memberStatus(member) === "active";
  const isCurrentUser = member.id === actorUserId;
  const currentRoleId = member.membership.roles[0]?.id ?? "";
  const pendingRole = roles.find((role) => role.id === pendingRoleId);
  const roleOptions = [
    ...(currentRoleId && !roles.some((role) => role.id === currentRoleId)
      ? [{ value: currentRoleId, label: `${roleNames(member)} (current role)` }]
      : []),
    ...roles.map((role) => ({ value: role.id, label: role.display_name })),
  ];

  const save = async (patch: Parameters<typeof workspaceDirectoryApi.saveMember>[1]) => {
    setBusy(true);
    setError(null);
    try {
      await workspaceDirectoryApi.saveMember(member.id, patch);
      onClose();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not save this member.";
      setError(message);
      throw new Error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      footer={<>
        <Button onClick={onClose} variant="secondary">Close</Button>
        {!isCurrentUser && (
          <Button loading={busy} onClick={() => setConfirmStatusChange(true)} variant={active ? "danger" : "secondary"}>
            {active ? "Suspend access" : "Restore access"}
          </Button>
        )}
      </>}
      onClose={onClose}
      open
      title={memberName(member)}
    >
      <div className="grid gap-4">
        <div className="flex items-center gap-3">
          <Avatar name={memberName(member)} size="lg" />
          <div>
            <p className="font-medium text-[var(--text-primary)]">{memberName(member)}</p>
            <p className="text-sm text-[var(--text-secondary)]">{member.email}</p>
          </div>
        </div>
        <label className="configuration-field">Workspace role
          <Select
            aria-describedby={isCurrentUser ? "own-access-help" : undefined}
            disabled={isCurrentUser}
            onChange={(event) => {
              if (event.target.value !== currentRoleId) setPendingRoleId(event.target.value);
            }}
            options={roleOptions}
            value={currentRoleId}
          />
        </label>
        {isCurrentUser && (
          <p className="text-sm text-[var(--text-secondary)]" id="own-access-help">
            Your workspace role and access can only be changed by another workspace administrator.
          </p>
        )}
        <div>
          <p className="mb-2 text-sm font-medium">Groups</p>
          <div className="flex flex-wrap gap-1">
            {member.groups.length
              ? member.groups.map((group) => <Badge key={group.id} tone="neutral">{group.display_name}</Badge>)
              : <span className="text-sm text-[var(--text-tertiary)]">No group memberships</span>}
          </div>
        </div>
        {error && <ErrorState description={error} layout="inline" />}
      </div>
      <ConfirmDialog
        confirmLabel="Change role"
        description={
          <>This changes {memberName(member)}’s workspace role to <strong>{pendingRole?.display_name}</strong>.</>
        }
        onClose={() => setPendingRoleId(null)}
        onConfirm={() => save({ role_ids: pendingRoleId ? [pendingRoleId] : [] })}
        open={pendingRoleId !== null}
        title="Change workspace role?"
      />
      <ConfirmDialog
        confirmLabel={active ? "Suspend access" : "Restore access"}
        description={
          active
            ? <>Suspending {memberName(member)} immediately removes their access to this workspace.</>
            : <>Restoring {memberName(member)} lets them access this workspace again with their assigned role.</>
        }
        destructive={active}
        onClose={() => setConfirmStatusChange(false)}
        onConfirm={() => save({ status: !active })}
        open={confirmStatusChange}
        title={active ? "Suspend workspace access?" : "Restore workspace access?"}
      />
    </Dialog>
  );
}

function AddMemberDialog({ open, roles, onClose }: { open: boolean; roles: Role[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = roleId || roles[0]?.id || "";

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await workspaceDirectoryApi.createMember({
        email: email.trim(),
        display_name: name.trim() || null,
        role_ids: chosen ? [chosen] : [],
      });
      setName("");
      setEmail("");
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add this member.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      footer={<>
        <Button onClick={onClose} variant="secondary">Cancel</Button>
        <Button disabled={!email.includes("@") || !chosen} loading={busy} onClick={submit}>Add member</Button>
      </>}
      onClose={onClose}
      open={open}
      title="Add member"
    >
      <div className="grid gap-4">
        <label className="configuration-field">Name
          <Input onChange={(event) => setName(event.target.value)} value={name} />
        </label>
        <label className="configuration-field">Email
          <Input onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
        </label>
        <label className="configuration-field">Role
          <Select
            onChange={(event) => setRoleId(event.target.value)}
            options={roles.map((role) => ({ value: role.id, label: role.display_name }))}
            value={chosen}
          />
        </label>
        {error && <ErrorState description={error} layout="inline" />}
      </div>
    </Dialog>
  );
}

function GroupsPanel({ rows }: { rows: Group[] }) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const matching = rows.filter((row) =>
    `${row.display_name} ${row.description ?? ""}`.toLowerCase().includes(search.toLowerCase()),
  );
  const columns: Column<Group>[] = [
    {
      key: "display_name",
      label: "Group",
      primary: true,
      sortable: true,
      render: (row) => <CellTitle subtitle={row.description ?? row.code} title={row.display_name} />,
    },
    { key: "member_count", label: "Members", width: 100, align: "right" },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={row.status} /> },
  ];

  return <>
    <CommandBar
      action={<Button icon={<Plus size={16} />} onClick={() => setOpen(true)}>Create group</Button>}
      count={`${matching.length} groups`}
      search={{ value: search, onChange: setSearch, placeholder: "Search groups…", label: "Search groups" }}
    />
    <DataTable
      ariaLabel="Access groups"
      columns={columns}
      data={matching}
      emptyState={<EmptyState description="Clear the search or create a group." icon={<UsersRound size={20} />} title="No matching groups" />}
    />
    <GroupDialog onClose={() => setOpen(false)} open={open} />
  </>;
}

function GroupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await workspaceDirectoryApi.createGroup({
        code: code.trim(),
        display_name: name.trim(),
        description: description.trim() || undefined,
      });
      setCode("");
      setName("");
      setDescription("");
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create this group.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      footer={<>
        <Button onClick={onClose} variant="secondary">Cancel</Button>
        <Button disabled={!code.trim() || !name.trim()} loading={busy} onClick={submit}>Create group</Button>
      </>}
      onClose={onClose}
      open={open}
      title="Create group"
    >
      <div className="grid gap-4">
        <label className="configuration-field">Group name
          <Input onChange={(event) => setName(event.target.value)} value={name} />
        </label>
        <label className="configuration-field">Code
          <Input onChange={(event) => setCode(event.target.value)} value={code} />
          <span className="text-xs text-[var(--text-tertiary)]">Short identifier, unique in this workspace.</span>
        </label>
        <label className="configuration-field">Description
          <Input onChange={(event) => setDescription(event.target.value)} value={description} />
        </label>
        {error && <ErrorState description={error} layout="inline" />}
      </div>
    </Dialog>
  );
}

function RolesPanel({ rows }: { rows: Role[] }) {
  const [open, setOpen] = useState(false);
  const columns: Column<Role>[] = [
    {
      key: "display_name",
      label: "Role",
      primary: true,
      sortable: true,
      render: (row) => <CellTitle subtitle={row.code} title={row.display_name} />,
    },
    {
      key: "permission_codes",
      label: "Permissions",
      priority: "medium",
      render: (row) => (
        <span className="flex flex-wrap gap-1">
          {row.permission_codes.slice(0, 3).map((permission) => (
            <Badge key={permission} tone="neutral">{permission}</Badge>
          ))}
          {row.permission_codes.length > 3 && (
            <span className="text-xs text-[var(--text-tertiary)]">
              +{row.permission_codes.length - 3} more
            </span>
          )}
        </span>
      ),
    },
    { key: "member_count", label: "Members", width: 100, align: "right" },
    { key: "is_system", label: "Type", width: 110, render: (row) => (row.is_system ? "Platform" : "Custom") },
  ];

  return <>
    <CommandBar
      action={<Button icon={<Plus size={16} />} onClick={() => setOpen(true)}>Create role</Button>}
      count={`${rows.length} roles`}
    />
    <DataTable
      ariaLabel="Workspace roles"
      columns={columns}
      data={rows}
      emptyState={<EmptyState description="Create a role to assign permissions." icon={<ShieldCheck size={20} />} title="No roles" />}
    />
    {open && <RoleDialog onClose={() => setOpen(false)} open />}
  </>;
}

function RoleDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const catalogue = useControlPlaneData(workspaceDirectoryApi.permissions);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choices: Permission[] = catalogue.data?.items ?? [];

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await workspaceDirectoryApi.createRole({
        code: code.trim(),
        display_name: name.trim(),
        permission_codes: permissions,
      });
      setCode("");
      setName("");
      setPermissions([]);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create this role.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      footer={<>
        <Button onClick={onClose} variant="secondary">Cancel</Button>
        <Button disabled={!code.trim() || !name.trim() || !permissions.length} loading={busy} onClick={submit}>
          Create role
        </Button>
      </>}
      onClose={onClose}
      open={open}
      title="Create role"
    >
      <div className="grid gap-4">
        <label className="configuration-field">Role name
          <Input onChange={(event) => setName(event.target.value)} value={name} />
        </label>
        <label className="configuration-field">Code
          <Input onChange={(event) => setCode(event.target.value)} value={code} />
        </label>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Permissions</legend>
          {catalogue.error ? (
            <ErrorState description={catalogue.error} layout="inline" onAction={catalogue.reload} />
          ) : catalogue.loading ? (
            <div aria-busy="true" className="grid gap-2" role="status">
              <span className="sr-only">Loading permissions</span>
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton className="h-10 w-full" key={index} />
              ))}
            </div>
          ) : (
            <div className="grid gap-2">
              {choices.map((permission) => (
                <label className="flex items-start gap-2 text-sm" key={permission.code}>
                  <input
                    checked={permissions.includes(permission.code)}
                    className="mt-1"
                    onChange={() => setPermissions((current) =>
                      current.includes(permission.code)
                        ? current.filter((item) => item !== permission.code)
                        : [...current, permission.code],
                    )}
                    type="checkbox"
                  />
                  <span>
                    <span className="font-medium">{permission.code}</span>
                    <span className="block text-xs text-[var(--text-tertiary)]">{permission.description}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </fieldset>
        {error && <ErrorState description={error} layout="inline" />}
      </div>
    </Dialog>
  );
}
