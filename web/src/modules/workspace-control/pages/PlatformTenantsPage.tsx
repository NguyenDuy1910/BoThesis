"use client";

import { Building2 } from "lucide-react";
import { useState } from "react";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { Button } from "@/components/ui/Button";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDateTime } from "@/modules/workspace-control/format";
import { workspaceDirectoryApi, type WorkspaceHealth } from "@/modules/workspace-control/directory";
import { useControlPlaneData } from "@/modules/workspace-control/queries";
import { ControlPlaneLoadingSkeleton } from "@/modules/workspace-control/components/ControlPlaneLoadingSkeleton";

/**
 * Every workspace on the platform, with the administrator behind it.
 *
 * Creating and suspending a workspace are not exposed by the API yet, so this
 * screen reports rather than acts: a button that could not complete would be
 * worse than none.
 */
export function PlatformTenantsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const query = useControlPlaneData(() => workspaceDirectoryApi.platform.workspaces(search));
  const [selected, setSelected] = useState<WorkspaceHealth | null>(null);
  const rows = (query.data?.items ?? []).filter((row) => !status || row.status === status);

  const columns: Column<WorkspaceHealth>[] = [
    {
      key: "name",
      label: "Workspace",
      primary: true,
      sortable: true,
      render: (row) => <CellTitle subtitle={row.code} title={row.name} />,
    },
    {
      key: "owner",
      label: "Administrator",
      priority: "medium",
      render: (row) => row.owner ? row.owner.display_name ?? row.owner.email : "None assigned",
    },
    { key: "member_count", label: "Members", width: 100, align: "right" },
    { key: "connection_count", label: "Connections", width: 120, align: "right", priority: "low" },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusBadge status={row.status} /> },
  ];

  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  if (!query.data) return <ControlPlaneLoadingSkeleton variant="platform-tenants" />;

  return <>
    <CommandBar
      count={`${rows.length} workspaces`}
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
      search={{ value: search, onChange: setSearch, placeholder: "Search workspaces…", label: "Search workspaces" }}
    />
    <DataTable
      ariaLabel="Platform workspaces"
      columns={columns}
      data={rows}
      emptyState={<EmptyState description="Clear the filters, or create a workspace from the API." icon={<Building2 size={20} />} title="No matching workspaces" />}
      onRowClick={setSelected}
    />
    <Dialog
      footer={<Button onClick={() => setSelected(null)} variant="secondary">Close</Button>}
      onClose={() => setSelected(null)}
      open={Boolean(selected)}
      title={selected?.name ?? ""}
    >
      {selected && (
        <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm">
          <dt className="text-[var(--text-tertiary)]">Code</dt><dd>{selected.code}</dd>
          <dt className="text-[var(--text-tertiary)]">Administrator</dt>
          <dd>{selected.owner ? `${selected.owner.display_name ?? "—"} · ${selected.owner.email}` : "None assigned"}</dd>
          <dt className="text-[var(--text-tertiary)]">Members</dt><dd>{selected.member_count}</dd>
          <dt className="text-[var(--text-tertiary)]">Connections</dt><dd>{selected.connection_count}</dd>
          <dt className="text-[var(--text-tertiary)]">Status</dt><dd><StatusBadge status={selected.status} /></dd>
          <dt className="text-[var(--text-tertiary)]">Created</dt><dd>{formatDateTime(selected.created_at)}</dd>
          <dt className="text-[var(--text-tertiary)]">Workspace ID</dt>
          <dd className="font-mono text-xs">{selected.id}</dd>
        </dl>
      )}
    </Dialog>
  </>;
}
