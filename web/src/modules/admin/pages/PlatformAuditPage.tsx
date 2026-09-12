"use client";

import { ScrollText } from "lucide-react";
import { useMemo, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { queryString, useAdminQuery } from "@/modules/admin/api";
import { describeAuditAction, formatRelative } from "@/modules/admin/format";

interface PlatformAuditEvent {
  [key: string]: unknown;
  id: string;
  action: string;
  outcome: string;
  created_at: string;
  workspace: { id: string; name: string };
  actor: { display_name?: string | null; email?: string | null } | null;
}
interface PlatformAudit { items: PlatformAuditEvent[]; total: number }

export function PlatformAuditPage() {
  const [search, setSearch] = useState("");
  const events = useAdminQuery<PlatformAudit>(`/platform/audit${queryString({ page_size: 50, search })}`);
  const columns = useMemo<Column<PlatformAuditEvent>[]>(() => [
    { key: "actor", label: "Actor", primary: true, render: (row) => { const name = row.actor?.display_name || row.actor?.email || "System"; return <CellTitle icon={<Avatar name={name} size="sm" />} subtitle={row.actor?.email} title={name} />; } },
    { key: "workspace", label: "Workspace", priority: "medium", render: (row) => row.workspace.name },
    { key: "action", label: "Action", render: (row) => describeAuditAction(row.action) },
    { key: "outcome", label: "Outcome", priority: "medium", width: 120, render: (row) => <StatusBadge status={row.outcome} /> },
    { key: "created_at", label: "When", priority: "low", width: 130, render: (row) => formatRelative(row.created_at) },
  ], []);
  if (events.error) return <ErrorState actionLabel="Try again" description={events.error} onAction={events.reload} title="Platform audit could not be loaded" />;
  return (
    <>
      <PageHeader eyebrow="PLATFORM ADMIN" description="Platform audit preserves actor identity and workspace context without exposing sensitive payloads." title="Platform audit" />
      <div className="mb-4"><SearchInput ariaLabel="Search platform audit" className="max-w-md" onChange={setSearch} placeholder="Search people, workspaces, or actions…" value={search} /></div>
      <DataTable ariaLabel="Platform audit events" columns={columns} data={events.data?.items ?? []} emptyState={<EmptyState description="Platform administrative events will appear here." icon={<ScrollText className="h-5 w-5" />} title="No platform audit events" />} />
    </>
  );
}
