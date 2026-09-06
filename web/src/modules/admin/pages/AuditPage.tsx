"use client";

import { ScrollText } from "lucide-react";
import { useMemo, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { queryString, useAdminQuery } from "@/modules/admin/api";
import type { Paginated } from "@/modules/admin/collections";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import {
  describeAuditAction,
  formatDateTime,
  formatRelative,
  pluralize,
  titleCase,
} from "@/modules/admin/format";

const PAGE_SIZE = 25;

interface AuditEvent extends Record<string, unknown> {
  id: string;
  action?: string;
  resource_type?: string;
  resource_id?: string;
  outcome?: string;
  created_at?: string;
  actor?: { display_name?: string | null; email?: string | null } | null;
  details?: Record<string, unknown> | null;
}

const resourceFilters = [
  { value: "", label: "Everything" },
  { value: "document", label: "Documents" },
  { value: "collection", label: "Collections" },
  { value: "user", label: "People" },
  { value: "group", label: "Groups" },
  { value: "role", label: "Roles" },
];

export function AuditPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [resource, setResource] = useState("");

  const events = useAdminQuery<Paginated<AuditEvent>>(
    `/audit-logs${queryString({
      page,
      page_size: PAGE_SIZE,
      search,
      resource_type: resource,
    })}`,
  );

  const columns = useMemo<Column<AuditEvent>[]>(
    () => [
      {
        key: "actor",
        label: "Who",
        render: (row) => {
          const name = row.actor?.display_name || row.actor?.email || "System";
          return (
            <CellTitle
              icon={<Avatar name={name} size="sm" />}
              subtitle={row.actor?.email ?? "Automated"}
              title={name}
            />
          );
        },
      },
      {
        key: "action",
        label: "What changed",
        minWidth: 240,
        render: (row) => (
          <span className="text-[var(--text)]">{describeAuditAction(row.action)}</span>
        ),
      },
      {
        key: "resource_type",
        label: "Area",
        priority: "low",
        width: 130,
        render: (row) => titleCase(row.resource_type) || "—",
      },
      {
        key: "outcome",
        priority: "medium",
        label: "Outcome",
        width: 120,
        render: (row) => <StatusBadge status={row.outcome} />,
      },
      {
        key: "created_at",
        priority: "medium",
        label: "When",
        width: 140,
        render: (row) => (
          <time dateTime={row.created_at} title={formatDateTime(row.created_at)}>
            {formatRelative(row.created_at)}
          </time>
        ),
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        description="An append-only record of every administrative change. Content and secrets are never stored here."
        metadata={events.data ? pluralize(events.data.total, "event") : undefined}
        title="Audit log"
      />

      <ResourceList
        ariaLabel="Audit log"
        columns={columns}
        empty={
          <EmptyState
            description="Uploads, access decisions and workspace changes are recorded here as they happen."
            icon={<ScrollText className="h-5 w-5" />}
            title="No events recorded yet"
          />
        }
        error={events.error}
        filtersActive={Boolean(search || resource)}
        loading={events.loading}
        onClearFilters={() => {
          setSearch("");
          setResource("");
          setPage(1);
        }}
        onRetry={events.reload}
        pagination={{
          page,
          pageSize: PAGE_SIZE,
          total: events.data?.total ?? 0,
          onPageChange: setPage,
        }}
        rows={events.data?.items ?? []}
        toolbar={
          <>
            <SearchInput
              ariaLabel="Search the audit log"
              className="w-full sm:w-72"
              onChange={(value) => {
                setSearch(value);
                setPage(1);
              }}
              placeholder="Search by person or action…"
              value={search}
            />
            <div className="adm-toolbar__spacer" />
            <Select
              aria-label="Filter by area"
              className="w-full sm:w-48"
              onChange={(event) => {
                setResource(event.target.value);
                setPage(1);
              }}
              options={resourceFilters}
              value={resource}
            />
          </>
        }
      />
    </>
  );
}
