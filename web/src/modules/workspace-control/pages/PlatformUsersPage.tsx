"use client";

import { ShieldCheck, Users } from "lucide-react";
import { useState } from "react";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CellTitle, DataTable, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { workspaceDirectoryApi, memberName, type PlatformUser } from "@/modules/workspace-control/directory";
import { useControlPlaneData } from "@/modules/workspace-control/queries";

/**
 * Identities across every workspace.
 *
 * Suspending someone is a workspace-scoped action, so it stays in that
 * workspace's Access screen rather than being offered here where it would
 * silently apply to only one of their memberships.
 */
export function PlatformUsersPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const users = useControlPlaneData(() => workspaceDirectoryApi.platform.users(search));
  const [selected, setSelected] = useState<PlatformUser | null>(null);
  const rows = (users.data?.items ?? []).filter(
    (row) => !status || String(row.status) === status,
  );

  const columns: Column<PlatformUser>[] = [
    {
      key: "email",
      label: "User",
      primary: true,
      sortable: true,
      render: (row) => (
        <CellTitle icon={<Avatar name={memberName(row)} size="md" />} subtitle={row.email} title={memberName(row)} />
      ),
    },
    {
      key: "memberships",
      label: "Workspaces",
      priority: "medium",
      render: (row) => row.memberships.length
        ? row.memberships.map((item) => item.workspace_name).join(", ")
        : "No membership",
    },
    {
      key: "platform_roles",
      label: "Platform scope",
      priority: "low",
      render: (row) => row.platform_roles.length
        ? <span className="flex flex-wrap gap-1">{row.platform_roles.map((role) => <Badge key={role} tone="info">{role}</Badge>)}</span>
        : "—",
    },
    {
      key: "status",
      label: "Status",
      width: 110,
      render: (row) => <StatusBadge status={row.status ? "active" : "suspended"} />,
    },
  ];

  if (users.error) return <ErrorState description={users.error} onAction={users.reload} />;

  return <>
    <CommandBar
      count={`${rows.length} users`}
      filters={
        <FilterTrigger
          label="Filter by status"
          onChange={setStatus}
          options={[
            { value: "", label: "All statuses" },
            { value: "true", label: "Active" },
            { value: "false", label: "Suspended" },
          ]}
          value={status}
        />
      }
      search={{ value: search, onChange: setSearch, placeholder: "Search users…", label: "Search platform users" }}
    />
    <DataTable
      ariaLabel="Platform users"
      columns={columns}
      data={rows}
      emptyState={<EmptyState description="Clear the search or status filter." icon={<Users size={20} />} title="No matching users" />}
      onRowClick={setSelected}
    />
    <Dialog
      footer={<Button onClick={() => setSelected(null)} variant="secondary">Close</Button>}
      onClose={() => setSelected(null)}
      open={Boolean(selected)}
      title={selected ? memberName(selected) : ""}
    >
      {selected && <>
        <div className="flex items-center gap-3">
          <Avatar name={memberName(selected)} size="lg" />
          <div>
            <p className="font-medium">{memberName(selected)}</p>
            <p className="text-sm text-[var(--text-secondary)]">{selected.email}</p>
          </div>
        </div>
        <dl className="mt-5 grid grid-cols-[8rem_1fr] gap-x-4 gap-y-3 text-sm">
          <dt className="text-[var(--text-tertiary)]">Workspaces</dt>
          <dd>
            {selected.memberships.length ? (
              <ul className="grid gap-1">
                {selected.memberships.map((item) => (
                  <li key={item.workspace_id}>
                    {item.workspace_name}
                    <span className="text-[var(--text-tertiary)]">
                      {item.role_names.length ? ` · ${item.role_names.join(", ")}` : " · no role"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : "No membership"}
          </dd>
          <dt className="text-[var(--text-tertiary)]">Platform scope</dt>
          <dd>
            {selected.platform_roles.length ? (
              <span className="inline-flex items-center gap-1">
                <ShieldCheck size={14} />{selected.platform_roles.join(", ")}
              </span>
            ) : "None"}
          </dd>
          <dt className="text-[var(--text-tertiary)]">Status</dt>
          <dd><StatusBadge status={selected.status ? "active" : "suspended"} /></dd>
          <dt className="text-[var(--text-tertiary)]">User ID</dt>
          <dd className="font-mono text-xs">{selected.id}</dd>
        </dl>
      </>}
    </Dialog>
  </>;
}
