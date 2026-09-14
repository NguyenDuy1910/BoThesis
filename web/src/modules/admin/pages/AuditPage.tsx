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
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { ActivityEvent } from "@/mocks/bothesis-api.mock";

export function AuditPage() {
  return <ActivityTable platform={false} />;
}

export function ActivityTable({ platform }: { platform: boolean }) {
  const events = useAdminData(() => adminData.activity.list(platform));
  const [search, setSearch] = useState("");
  const [outcome, setOutcome] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [selected, setSelected] = useState<ActivityEvent | null>(null);
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (events.data ?? []).filter((row) =>
      (!term || `${row.actor} ${row.action} ${row.resource}`.toLowerCase().includes(term))
      && (!outcome || row.status === outcome)
      && (!workspace || row.workspace === workspace),
    );
  }, [events.data, outcome, search, workspace]);
  const workspaces = Array.from(new Set((events.data ?? []).map((row) => row.workspace)));
  const columns: Column<ActivityEvent>[] = [
    { key: "actor", label: "Actor", primary: true, sortable: true, render: (row) => <CellTitle icon={<Avatar name={row.actor} size="sm" />} title={row.actor} subtitle={row.resource} /> },
    ...(platform ? [{ key: "workspace", label: "Workspace", priority: "medium" as const, width: 140 }] : []),
    { key: "action", label: "Activity", minWidth: 220 },
    { key: "status", label: "Outcome", width: 110, render: (row) => <StatusBadge status={row.status === "danger" ? "failed" : row.status} /> },
    { key: "time", label: "When", width: 140, priority: "medium" },
  ];

  if (events.error) return <ErrorState description={events.error} onAction={events.reload} />;

  return <>
    <CommandBar
      search={{ value: search, onChange: setSearch, placeholder: "Search activity…", label: "Search activity" }}
      filters={<>
        {platform && <FilterTrigger label="Filter by workspace" value={workspace} onChange={setWorkspace} options={[{ value: "", label: "All workspaces" }, ...workspaces.map((value) => ({ value, label: value.toUpperCase() }))]} />}
        <FilterTrigger label="Filter by outcome" value={outcome} onChange={setOutcome} options={[{ value: "", label: "All outcomes" }, { value: "success", label: "Success" }, { value: "warning", label: "Warning" }, { value: "danger", label: "Failed" }]} />
      </>}
      count={`${rows.length} events`}
    />
    <DataTable ariaLabel={platform ? "Platform activity" : "Workspace activity"} columns={columns} data={rows} onRowClick={setSelected} emptyState={<EmptyState icon={<ScrollText size={20} />} title="No matching activity" description="Administrative changes and sync events appear here without private content." />} />
    <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} title="Activity details">
      {selected && <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm">
        <dt className="text-[var(--text-tertiary)]">Actor</dt><dd>{selected.actor}</dd>
        <dt className="text-[var(--text-tertiary)]">Action</dt><dd>{selected.action}</dd>
        <dt className="text-[var(--text-tertiary)]">Resource</dt><dd>{selected.resource}</dd>
        <dt className="text-[var(--text-tertiary)]">Workspace</dt><dd>{selected.workspace}</dd>
        <dt className="text-[var(--text-tertiary)]">Outcome</dt><dd><StatusBadge status={selected.status === "danger" ? "failed" : selected.status} /></dd>
        <dt className="text-[var(--text-tertiary)]">Recorded</dt><dd>{selected.time}</dd>
        <dt className="text-[var(--text-tertiary)]">Event ID</dt><dd className="font-mono text-xs">{selected.id}</dd>
      </dl>}
    </Dialog>
  </>;
}
