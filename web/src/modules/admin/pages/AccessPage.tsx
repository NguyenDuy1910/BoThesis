"use client";

import { Plus, ShieldCheck, UserPlus, Users, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";

import { FilterTrigger, CommandBar } from "@/components/layout/CommandBar";
import { SettingRow, Toggle } from "@/components/patterns";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { AccessGroup, AccessPolicy, AccessRole, Member } from "@/mocks/bothesis-api.mock";

type AccessTab = "policy" | "members" | "groups" | "roles";

const tabs = [
  { id: "policy", label: "Policy" },
  { id: "members", label: "Members" },
  { id: "groups", label: "Groups" },
  { id: "roles", label: "Roles" },
];

export function AccessPage() {
  const [routeTab, setRouteTab] = useRouteState("tab", "policy");
  const tab = tabs.some((item) => item.id === routeTab) ? routeTab as AccessTab : "policy";
  const policy = useAdminData(adminData.access.policy);
  const members = useAdminData(adminData.access.members);
  const groups = useAdminData(adminData.access.groups);
  const roles = useAdminData(adminData.access.roles);
  const error = policy.error || members.error || groups.error || roles.error;

  if (error) {
    return <ErrorState description={error} onAction={() => { policy.reload(); members.reload(); groups.reload(); roles.reload(); }} />;
  }

  return <>
    <Tabs activeTab={tab} ariaLabel="Access sections" className="mb-4" onChange={setRouteTab} tabs={tabs} />
    {tab === "policy" && policy.data && <PolicyPanel initial={policy.data} />}
    {tab === "members" && <MembersPanel rows={members.data ?? []} roles={roles.data ?? []} />}
    {tab === "groups" && <GroupsPanel rows={groups.data ?? []} roles={roles.data ?? []} />}
    {tab === "roles" && <RolesPanel rows={roles.data ?? []} />}
  </>;
}

function PolicyPanel({ initial }: { initial: AccessPolicy }) {
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(value) !== JSON.stringify(saved);
  const save = async () => {
    setBusy(true);
    const next = await adminData.access.savePolicy(value);
    setSaved(next);
    setBusy(false);
  };

  return <div className="mx-auto grid max-w-3xl gap-4">
    <Card>
      <CardHeader title="Workspace access" description="Choose who can open this workspace. Source-level permissions still decide which documents a person can retrieve." />
      <CardBody className="grid gap-3">
        <label className="configuration-field">Who can open this workspace
          <Select aria-label="Who can open this workspace" value={value.workspaceAccess} onChange={(event) => setValue({ ...value, workspaceAccess: event.target.value as AccessPolicy["workspaceAccess"] })} options={[
            { value: "members", label: "Members only" },
            { value: "everyone", label: "Everyone using BoThesis" },
          ]} />
        </label>
        <label className="configuration-field">Who can invite members
          <Select aria-label="Who can invite members" value={value.invitations} onChange={(event) => setValue({ ...value, invitations: event.target.value as AccessPolicy["invitations"] })} options={[
            { value: "admins", label: "Owners and admins" },
            { value: "members", label: "All members" },
          ]} />
        </label>
      </CardBody>
    </Card>
    <Card>
      <CardHeader title="Discovery and entry" description="Being listed does not grant membership or document access. The platform default is managed separately by a platform administrator." />
      <CardBody className="divide-y divide-[var(--border-subtle)]">
        <SettingRow title="Discoverable" description="Show this workspace in Explore workspaces to people who can request or already have access." control={<Toggle checked={value.discoverable} label="Make workspace discoverable" onChange={(discoverable) => setValue({ ...value, discoverable })} />} />
        <SettingRow disabled title="Platform default" description="Open this workspace for a signed-in user who has no membership yet." note="Managed in Platform Admin → Public Workspaces." control={<Toggle checked={value.platformDefault} disabled label="Platform default workspace" />} />
      </CardBody>
    </Card>
    <Card>
      <CardHeader title="Knowledge enforcement" description="These controls apply before results or citations reach the agent." />
      <CardBody className="divide-y divide-[var(--border-subtle)]">
        <SettingRow title="Respect source permissions" description="Only retrieve documents the current member can access at the source." control={<Toggle checked={value.sourcePermissions} label="Respect source permissions" onChange={(sourcePermissions) => setValue({ ...value, sourcePermissions })} />} />
        <SettingRow title="Guest access" description="Allow invited guests to use knowledge explicitly shared with them." control={<Toggle checked={value.guestAccess} label="Allow guest access" onChange={(guestAccess) => setValue({ ...value, guestAccess })} />} />
      </CardBody>
    </Card>
    <div className="flex items-center justify-end gap-2"><Button variant="ghost" disabled={!dirty} onClick={() => setValue(saved)}>Discard</Button><Button disabled={!dirty} loading={busy} onClick={save}>Save policy</Button></div>
  </div>;
}

function MembersPanel({ rows, roles }: { rows: Member[]; roles: AccessRole[] }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Member | null>(null);
  const matching = useMemo(() => rows.filter((row) => {
    const term = search.toLowerCase();
    return (!term || `${row.name} ${row.email} ${row.role}`.toLowerCase().includes(term)) && (!status || row.status === status);
  }), [rows, search, status]);
  const columns: Column<Member>[] = [
    { key: "name", label: "Member", primary: true, sortable: true, render: (row) => <CellTitle icon={<Avatar name={row.name} size="md" />} title={row.name} subtitle={row.email} /> },
    { key: "role", label: "Workspace role", priority: "medium" },
    { key: "groups", label: "Knowledge access", priority: "low", render: (row) => row.groups.join(", ") || "Direct access only" },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={row.status} /> },
  ];

  return <>
    <CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search members…", label: "Search members" }} filters={<FilterTrigger label="Filter by status" value={status} onChange={setStatus} options={[{ value: "", label: "All statuses" }, { value: "active", label: "Active" }, { value: "invited", label: "Invited" }, { value: "suspended", label: "Suspended" }]} />} count={`${matching.length} members`} action={<Button icon={<UserPlus size={16} />} onClick={() => setOpen(true)}>Invite member</Button>} />
    <DataTable ariaLabel="Workspace members" columns={columns} data={matching} onRowClick={setSelected} emptyState={<EmptyState icon={<Users size={20} />} title="No matching members" description="Clear the filters or invite a new member." />} />
    <MemberDialog member={selected} roles={roles} onClose={() => setSelected(null)} />
    <InviteDialog open={open} roles={roles} onClose={() => setOpen(false)} />
  </>;
}

function MemberDialog({ member, roles, onClose }: { member: Member | null; roles: AccessRole[]; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  if (!member) return null;
  const save = async (patch: Partial<Member>) => { setBusy(true); await adminData.access.saveMember({ ...member, ...patch }); setBusy(false); onClose(); };
  return <Dialog open title={member.name} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button variant={member.status === "suspended" ? "secondary" : "danger"} loading={busy} onClick={() => save({ status: member.status === "suspended" ? "active" : "suspended" })}>{member.status === "suspended" ? "Restore access" : "Suspend access"}</Button></>}>
    <div className="grid gap-4"><div className="flex items-center gap-3"><Avatar name={member.name} size="lg" /><div><p className="font-medium text-[var(--text-primary)]">{member.name}</p><p className="text-sm text-[var(--text-secondary)]">{member.email}</p></div></div><label className="configuration-field">Workspace role<Select value={member.role} onChange={(event) => save({ role: event.target.value })} options={roles.map((role) => ({ value: role.name, label: role.name }))} /></label><div><p className="mb-2 text-sm font-medium">Knowledge groups</p><div className="flex flex-wrap gap-1">{member.groups.length ? member.groups.map((group) => <Badge key={group} tone="neutral">{group}</Badge>) : <span className="text-sm text-[var(--text-tertiary)]">No group memberships</span>}</div></div></div>
  </Dialog>;
}

function InviteDialog({ open, roles, onClose }: { open: boolean; roles: AccessRole[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("Member");
  const [busy, setBusy] = useState(false);
  const submit = async () => { setBusy(true); await adminData.access.saveMember({ id: crypto.randomUUID(), name: name.trim() || email.split("@")[0], email: email.trim(), role, status: "invited", groups: [], workspaceId: adminData.session.current()?.active_tenant_id ?? "spkt" }); setBusy(false); setName(""); setEmail(""); onClose(); };
  return <Dialog open={open} onClose={onClose} title="Invite member" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!email.includes("@")} onClick={submit}>Send invite</Button></>}><div className="grid gap-4"><label className="configuration-field">Name<Input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="configuration-field">Email<Input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label className="configuration-field">Role<Select value={role} onChange={(event) => setRole(event.target.value)} options={roles.map((item) => ({ value: item.name, label: item.name }))} /></label></div></Dialog>;
}

function GroupsPanel({ rows, roles }: { rows: AccessGroup[]; roles: AccessRole[] }) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const matching = rows.filter((row) => `${row.name} ${row.description}`.toLowerCase().includes(search.toLowerCase()));
  const columns: Column<AccessGroup>[] = [
    { key: "name", label: "Group", primary: true, sortable: true, render: (row) => <CellTitle title={row.name} subtitle={row.description} /> },
    { key: "members", label: "Members", width: 100, align: "right" },
    { key: "role", label: "Default role", width: 140 },
  ];
  return <><CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search groups…", label: "Search groups" }} count={`${matching.length} groups`} action={<Button icon={<Plus size={16} />} onClick={() => setOpen(true)}>Create group</Button>} /><DataTable ariaLabel="Access groups" columns={columns} data={matching} emptyState={<EmptyState icon={<UsersRound size={20} />} title="No matching groups" description="Clear the search or create a group." />} /><GroupDialog open={open} roles={roles} onClose={() => setOpen(false)} /></>;
}

function GroupDialog({ open, roles, onClose }: { open: boolean; roles: AccessRole[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [role, setRole] = useState("Member");
  const submit = async () => { await adminData.access.saveGroup({ id: crypto.randomUUID(), name: name.trim(), description: description.trim(), members: 0, role }); setName(""); setDescription(""); onClose(); };
  return <Dialog open={open} onClose={onClose} title="Create group" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!name.trim()} onClick={submit}>Create group</Button></>}><div className="grid gap-4"><label className="configuration-field">Group name<Input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="configuration-field">Description<Input value={description} onChange={(event) => setDescription(event.target.value)} /></label><label className="configuration-field">Default role<Select value={role} onChange={(event) => setRole(event.target.value)} options={roles.map((item) => ({ value: item.name, label: item.name }))} /></label></div></Dialog>;
}

function RolesPanel({ rows }: { rows: AccessRole[] }) {
  const [open, setOpen] = useState(false);
  const columns: Column<AccessRole>[] = [
    { key: "name", label: "Role", primary: true, sortable: true, render: (row) => <CellTitle title={row.name} subtitle={row.description} /> },
    { key: "permissions", label: "Permissions", priority: "medium", render: (row) => <span className="flex flex-wrap gap-1">{row.permissions.slice(0, 3).map((permission) => <Badge key={permission} tone="neutral">{permission}</Badge>)}</span> },
    { key: "builtIn", label: "Type", width: 110, render: (row) => row.builtIn ? "Built-in" : "Custom" },
  ];
  return <><CommandBar count={`${rows.length} roles`} action={<Button icon={<Plus size={16} />} onClick={() => setOpen(true)}>Create role</Button>} /><DataTable ariaLabel="Workspace roles" columns={columns} data={rows} emptyState={<EmptyState icon={<ShieldCheck size={20} />} title="No roles" description="Create a role to assign permissions." />} /><RoleDialog open={open} onClose={() => setOpen(false)} /></>;
}

function RoleDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [permissions, setPermissions] = useState(["Use workspace"]);
  const choices = ["Use workspace", "Manage knowledge", "Configure agent", "Manage access", "Manage workspace"];
  const submit = async () => { await adminData.access.saveRole({ id: crypto.randomUUID(), name: name.trim(), description: description.trim(), permissions, builtIn: false }); setName(""); setDescription(""); setPermissions(["Use workspace"]); onClose(); };
  return <Dialog open={open} onClose={onClose} title="Create role" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!name.trim() || !permissions.length} onClick={submit}>Create role</Button></>}><div className="grid gap-4"><label className="configuration-field">Role name<Input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="configuration-field">Description<Input value={description} onChange={(event) => setDescription(event.target.value)} /></label><fieldset><legend className="mb-2 text-sm font-medium">Permissions</legend><div className="grid gap-2">{choices.map((permission) => <label className="flex items-center gap-2 text-sm" key={permission}><input type="checkbox" checked={permissions.includes(permission)} onChange={() => setPermissions((current) => current.includes(permission) ? current.filter((item) => item !== permission) : [...current, permission])} />{permission}</label>)}</div></fieldset></div></Dialog>;
}
