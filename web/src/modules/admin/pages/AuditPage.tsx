"use client";

import { ScrollText } from "lucide-react";
import { useMemo, useState } from "react";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { Avatar } from "@/components/ui/Avatar";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { describeAuditAction, formatDateTime, formatRelative } from "@/modules/admin/format";
import { directoryApi, type AuditEvent } from "@/modules/admin/directory";
import { useAdminData } from "@/modules/admin/queries";

export function AuditPage() {
  return <ActivityTable platform={false} />;
}

/** Who did what, where, and how it went — from the durable audit trail. */
export function ActivityTable({ platform }: { platform: boolean }) {
  const [search, setSearch] = useState("");
  const events = useAdminData(async () =>
    platform ? directoryApi.platform.audit(search) : directoryApi.auditLogs(search),
  );
  const [outcome, setOutcome] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const items = useMemo(() => events.data?.items ?? [], [events.data]);
  const rows = useMemo(
    () => items.filter((row) =>
      (!outcome || row.outcome === outcome)
      && (!workspace || row.workspace?.id === workspace),
    ),
    [items, outcome, workspace],
  );
  const workspaces = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of items) {
      if (row.workspace) seen.set(row.workspace.id, row.workspace.name ?? row.workspace.id);
    }
    return [...seen.entries()];
  }, [items]);

  const actorOf = (row: AuditEvent) =>
    row.actor.display_name ?? row.actor.email ?? "System";

  const columns: Column<AuditEvent>[] = [
    {
      key: "actor",
      label: "Actor",
      primary: true,
      sortable: true,
      render: (row) => (
        <CellTitle
          icon={<Avatar name={actorOf(row)} size="sm" />}
          subtitle={row.resource_id ?? row.resource_type}
          title={actorOf(row)}
        />
      ),
    },
    ...(platform
      ? [{
          key: "workspace",
          label: "Workspace",
          priority: "medium" as const,
          width: 160,
          render: (row: AuditEvent) => row.workspace?.name ?? "Platform",
        }]
      : []),
    { key: "action", label: "Activity", minWidth: 220, render: (row) => describeAuditAction(row.action) },
    {
      key: "outcome",
      label: "Outcome",
      width: 110,
      render: (row) => <StatusBadge status={row.outcome === "success" ? "success" : "failed"} />,
    },
    {
      key: "created_at",
      label: "When",
      width: 140,
      priority: "medium",
      render: (row) => <span title={formatDateTime(row.created_at)}>{formatRelative(row.created_at)}</span>,
    },
  ];

  if (events.error) return <ErrorState description={events.error} onAction={events.reload} />;

  return <>
    <CommandBar
      count={`${rows.length} events`}
      filters={<>
        {platform && (
          <FilterTrigger
            label="Filter by workspace"
            onChange={setWorkspace}
            options={[{ value: "", label: "All workspaces" }, ...workspaces.map(([value, label]) => ({ value, label }))]}
            value={workspace}
          />
        )}
        <FilterTrigger
          label="Filter by outcome"
          onChange={setOutcome}
          options={[
            { value: "", label: "All outcomes" },
            { value: "success", label: "Success" },
            { value: "failure", label: "Failed" },
          ]}
          value={outcome}
        />
      </>}
      search={{ value: search, onChange: setSearch, placeholder: "Search activity…", label: "Search activity" }}
    />
    <DataTable
      ariaLabel={platform ? "Platform activity" : "Workspace activity"}
      columns={columns}
      data={rows}
      emptyState={<EmptyState description="Administrative changes and sync events appear here without private content." icon={<ScrollText size={20} />} title="No matching activity" />}
      onRowClick={setSelected}
    />
    <Dialog onClose={() => setSelected(null)} open={Boolean(selected)} title="Activity details">
      {selected && (
        <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm">
          <dt className="text-[var(--text-tertiary)]">Actor</dt><dd>{actorOf(selected)}</dd>
          <dt className="text-[var(--text-tertiary)]">Action</dt><dd className="font-mono text-xs">{selected.action}</dd>
          <dt className="text-[var(--text-tertiary)]">Resource</dt>
          <dd>{selected.resource_type}{selected.resource_id ? ` · ${selected.resource_id}` : ""}</dd>
          <dt className="text-[var(--text-tertiary)]">Workspace</dt>
          <dd>{selected.workspace ? selected.workspace.name ?? selected.workspace.id : "Platform"}</dd>
          <dt className="text-[var(--text-tertiary)]">Outcome</dt>
          <dd><StatusBadge status={selected.outcome === "success" ? "success" : "failed"} /></dd>
          <dt className="text-[var(--text-tertiary)]">Recorded</dt><dd>{formatDateTime(selected.created_at)}</dd>
          <dt className="text-[var(--text-tertiary)]">Event ID</dt><dd className="font-mono text-xs">{selected.id}</dd>
        </dl>
      )}
    </Dialog>
  </>;
}
