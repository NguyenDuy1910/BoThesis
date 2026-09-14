"use client";

import { Building2, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { Button } from "@/components/ui/Button";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { Workspace } from "@/mocks/bothesis-api.mock";

export function PlatformTenantsPage() {
  const query = useAdminData(adminData.workspaces.list);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Workspace | null>(null);
  const [creating, setCreating] = useState(false);
  const rows = useMemo(() => (query.data ?? []).filter((row) => {
    const term = search.toLowerCase();
    return (!term || `${row.name} ${row.organization} ${row.description}`.toLowerCase().includes(term)) && (!status || row.status === status);
  }), [query.data, search, status]);
  const columns: Column<Workspace>[] = [
    { key: "name", label: "Tenant", primary: true, sortable: true, render: (row) => <CellTitle title={row.name} subtitle={row.organization} /> },
    { key: "access", label: "Access", width: 140, priority: "medium", render: (row) => row.access === "everyone" ? "Public" : "Members only" },
    { key: "discoverable", label: "Directory", width: 120, priority: "low", render: (row) => row.discoverable ? "Listed" : "Hidden" },
    { key: "isDefault", label: "Landing", width: 100, render: (row) => row.isDefault ? "Default" : "—" },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={row.status} /> },
  ];
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  return <>
    <CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search tenants…", label: "Search tenants" }} filters={<FilterTrigger label="Filter by status" value={status} onChange={setStatus} options={[{ value: "", label: "All statuses" }, { value: "active", label: "Active" }, { value: "suspended", label: "Suspended" }]} />} count={`${rows.length} tenants`} action={<Button icon={<Plus size={16} />} onClick={() => setCreating(true)}>New tenant</Button>} />
    <DataTable ariaLabel="Platform tenants" columns={columns} data={rows} onRowClick={setSelected} emptyState={<EmptyState icon={<Building2 size={20} />} title="No matching tenants" description="Clear the filters or create a tenant." />} />
    <TenantDialog tenant={selected} onClose={() => setSelected(null)} />
    <CreateTenantDialog open={creating} onClose={() => setCreating(false)} />
  </>;
}

function TenantDialog({ tenant, onClose }: { tenant: Workspace | null; onClose: () => void }) {
  if (!tenant) return null;
  const save = async (patch: Partial<Workspace>) => { await adminData.workspaces.save(tenant.id, patch); onClose(); };
  return <Dialog open title={tenant.name} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button variant={tenant.status === "active" ? "danger" : "secondary"} onClick={() => save({ status: tenant.status === "active" ? "suspended" : "active" })}>{tenant.status === "active" ? "Suspend tenant" : "Restore tenant"}</Button></>}>
    <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-3 text-sm"><dt className="text-[var(--text-tertiary)]">Organization</dt><dd>{tenant.organization}</dd><dt className="text-[var(--text-tertiary)]">Access</dt><dd>{tenant.access === "everyone" ? "Everyone signed in" : "Members only"}</dd><dt className="text-[var(--text-tertiary)]">Directory</dt><dd>{tenant.discoverable ? "Listed" : "Hidden"}</dd><dt className="text-[var(--text-tertiary)]">Tenant ID</dt><dd className="font-mono text-xs">{tenant.id}</dd></dl>
    {!tenant.isDefault && <Button className="mt-5" variant="secondary" onClick={() => save({ isDefault: true, discoverable: true, access: "everyone" })}>Make landing tenant</Button>}
  </Dialog>;
}

function CreateTenantDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const [organization, setOrganization] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => { setBusy(true); await adminData.workspaces.create(name.trim(), organization.trim()); setBusy(false); setName(""); setOrganization(""); onClose(); };
  return <Dialog open={open} title="New tenant" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!name.trim() || !organization.trim()} onClick={create}>Create tenant</Button></>}><div className="grid gap-4"><label className="configuration-field">Tenant name<Input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="configuration-field">Organization<Input value={organization} onChange={(event) => setOrganization(event.target.value)} /></label></div></Dialog>;
}
