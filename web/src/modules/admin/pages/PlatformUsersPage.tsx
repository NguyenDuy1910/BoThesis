"use client";

import { ShieldCheck, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { Member, Workspace } from "@/mocks/bothesis-api.mock";

export function PlatformUsersPage() {
  const users = useAdminData(() => adminData.access.members(true));
  const tenants = useAdminData(adminData.workspaces.list);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Member | null>(null);
  const tenantNames = new Map((tenants.data ?? []).map((tenant) => [tenant.id, tenant.name]));
  const rows = useMemo(() => (users.data ?? []).filter((row) => {
    const term = search.toLowerCase();
    return (!term || `${row.name} ${row.email} ${row.role}`.toLowerCase().includes(term)) && (!status || row.status === status);
  }), [search, status, users.data]);
  const columns: Column<Member>[] = [
    { key: "name", label: "User", primary: true, sortable: true, render: (row) => <CellTitle icon={<Avatar name={row.name} size="md" />} title={row.name} subtitle={row.email} /> },
    { key: "workspaceId", label: "Membership", priority: "medium", render: (row) => `${tenantNames.get(row.workspaceId) ?? row.workspaceId} · ${row.role}` },
    { key: "role", label: "Platform scope", priority: "low", render: (row) => row.id === "duy" ? <Badge tone="info">Root access</Badge> : "—" },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={row.status} /> },
  ];
  if (users.error || tenants.error) return <ErrorState description={users.error || tenants.error || ""} onAction={() => { users.reload(); tenants.reload(); }} />;
  return <>
    <CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search users…", label: "Search platform users" }} filters={<FilterTrigger label="Filter by status" value={status} onChange={setStatus} options={[{ value: "", label: "All statuses" }, { value: "active", label: "Active" }, { value: "invited", label: "Invited" }, { value: "suspended", label: "Suspended" }]} />} count={`${rows.length} users`} />
    <DataTable ariaLabel="Platform users" columns={columns} data={rows} onRowClick={setSelected} emptyState={<EmptyState icon={<Users size={20} />} title="No matching users" description="Clear the search or status filter." />} />
    <UserDialog user={selected} tenant={selected ? tenants.data?.find((item) => item.id === selected.workspaceId) ?? null : null} onClose={() => setSelected(null)} />
  </>;
}

function UserDialog({ user, tenant, onClose }: { user: Member | null; tenant: Workspace | null; onClose: () => void }) {
  if (!user) return null;
  const toggle = async () => { await adminData.access.saveMember({ ...user, status: user.status === "suspended" ? "active" : "suspended" }); onClose(); };
  return <Dialog open title={user.name} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button variant={user.status === "suspended" ? "secondary" : "danger"} disabled={user.id === "duy"} onClick={toggle}>{user.status === "suspended" ? "Restore user" : "Suspend user"}</Button></>}>
    <div className="flex items-center gap-3"><Avatar name={user.name} size="lg" /><div><p className="font-medium">{user.name}</p><p className="text-sm text-[var(--text-secondary)]">{user.email}</p></div></div>
    <dl className="mt-5 grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm"><dt className="text-[var(--text-tertiary)]">Workspace</dt><dd>{tenant?.name ?? user.workspaceId}</dd><dt className="text-[var(--text-tertiary)]">Role</dt><dd>{user.role}</dd><dt className="text-[var(--text-tertiary)]">Platform scope</dt><dd>{user.id === "duy" ? <span className="inline-flex items-center gap-1"><ShieldCheck size={14} />Root admin</span> : "None"}</dd><dt className="text-[var(--text-tertiary)]">Status</dt><dd><StatusBadge status={user.status} /></dd></dl>
  </Dialog>;
}
