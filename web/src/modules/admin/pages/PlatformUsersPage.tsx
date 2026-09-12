"use client";

import { ShieldCheck, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { queryString, useAdminQuery } from "@/modules/admin/api";

interface PlatformUser {
  [key: string]: unknown;
  id: string;
  email: string;
  display_name: string | null;
  status: boolean;
  platform_scopes: string[];
  memberships: { workspace_id: string; workspace_name: string; role_name: string }[];
}

interface PlatformUsers { items: PlatformUser[]; total: number }

export function PlatformUsersPage() {
  const [search, setSearch] = useState("");
  const list = useAdminQuery<PlatformUsers>(`/platform/users${queryString({ page_size: 50, search })}`);
  const columns = useMemo<Column<PlatformUser>[]>(() => [
    { key: "display_name", label: "User", primary: true, render: (row) => <CellTitle subtitle={row.email} title={row.display_name || row.email} /> },
    { key: "memberships", label: "Workspace memberships", priority: "medium", render: (row) => row.memberships.length ? row.memberships.map((membership) => `${membership.workspace_name} · ${membership.role_name}`).join(", ") : "No active workspace" },
    { key: "platform_scopes", label: "Platform scope", priority: "medium", render: (row) => row.platform_scopes.length ? <Badge tone="info">Root access</Badge> : "—" },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusBadge status={row.status ? "active" : "inactive"} /> },
  ], []);
  if (list.error) return <ErrorState actionLabel="Try again" description={list.error} onAction={list.reload} title="Platform users could not be loaded" />;
  return (
    <>
      <PageHeader eyebrow="PLATFORM ADMIN" description="A user may belong to multiple workspaces; platform root scope remains separate from each workspace role." title="Users" />
      <div className="mb-4"><SearchInput ariaLabel="Search platform users" className="max-w-md" onChange={setSearch} placeholder="Search users…" value={search} /></div>
      <DataTable ariaLabel="Platform users" columns={columns} data={list.data?.items ?? []} emptyState={<EmptyState description="No user matches the current search." icon={<Users className="h-5 w-5" />} title="No users found" />} />
      <p className="mt-4 flex items-start gap-2 rounded-[var(--radius-md)] bg-[var(--status-info-bg)] px-3.5 py-3 text-[0.8125rem] text-[var(--status-info-text)]"><ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />Platform root access is an authorization scope on the same user identity; it does not replace membership roles.</p>
    </>
  );
}
