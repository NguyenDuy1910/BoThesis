"use client";

import { Building2 } from "lucide-react";
import { useMemo, useState } from "react";

import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { queryString, useAdminQuery } from "@/modules/admin/api";
import { formatDateTime } from "@/modules/admin/format";

interface WorkspaceRow {
  [key: string]: unknown;
  id: string;
  name: string;
  code: string;
  status: string;
  created_at: string;
  member_count: number;
  connection_count: number;
  owner: { display_name?: string | null; email?: string | null } | null;
}

interface WorkspaceDirectory {
  items: WorkspaceRow[];
  total: number;
}

export function PlatformWorkspacesPage() {
  const [search, setSearch] = useState("");
  const list = useAdminQuery<WorkspaceDirectory>(`/platform/workspaces${queryString({ page_size: 50, search })}`);
  const columns = useMemo<Column<WorkspaceRow>[]>(() => [
    { key: "name", label: "Workspace", primary: true, render: (row) => <CellTitle subtitle={row.code} title={row.name} /> },
    { key: "owner", label: "Owner", priority: "medium", render: (row) => row.owner?.display_name || row.owner?.email || "Not assigned" },
    { key: "member_count", label: "Members", align: "right", width: 100, render: (row) => row.member_count.toLocaleString() },
    { key: "connection_count", label: "Connections", align: "right", priority: "medium", width: 120, render: (row) => row.connection_count.toLocaleString() },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusBadge status={row.status} /> },
    { key: "created_at", label: "Created", priority: "low", width: 150, render: (row) => formatDateTime(row.created_at) },
  ], []);

  if (list.error) return <ErrorState actionLabel="Try again" description={list.error} onAction={list.reload} title="Workspaces could not be loaded" />;

  return (
    <>
      <PageHeader eyebrow="PLATFORM ADMIN" description="Review every workspace, its owner, membership, connection health, and lifecycle state." title="Workspaces" />
      <div className="mb-4 flex flex-col gap-2 rounded-[var(--radius-md)] bg-[var(--surface-base)] p-3 shadow-[inset_0_0_0_1px_var(--border-subtle)] sm:flex-row">
        <SearchInput ariaLabel="Search workspaces" className="max-w-md" onChange={setSearch} placeholder="Search workspace…" value={search} />
      </div>
      <DataTable
        ariaLabel="Platform workspaces"
        columns={columns}
        data={list.data?.items ?? []}
        emptyState={<EmptyState description="No workspace matches the current search." icon={<Building2 className="h-5 w-5" />} title="No workspaces found" />}
      />
    </>
  );
}
