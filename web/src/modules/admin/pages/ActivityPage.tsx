"use client";

import { Ban, Plug, RotateCw, Waypoints } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Segmented } from "@/components/ui/Segmented";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { Tooltip } from "@/components/ui/Tooltip";
import { adminRequest, queryString, useAdminQuery } from "@/modules/admin/api";
import type { IngestionRun, Paginated } from "@/modules/admin/collections";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import {
  errorMessage,
  formatRelative,
  pluralize,
  titleCase,
} from "@/modules/admin/format";

const PAGE_SIZE = 25;

type RunFilter = "" | "running" | "completed" | "failed";

const filters: { value: RunFilter; label: string }[] = [
  { value: "", label: "All runs" },
  { value: "running", label: "In progress" },
  { value: "completed", label: "Succeeded" },
  { value: "failed", label: "Failed" },
];

const triggerLabels: Record<string, string> = {
  manual: "Started by a person",
  scheduled: "On a schedule",
  webhook: "Triggered by the source",
  initial: "First import",
};

/** How long a run took, or how long it has been going. */
function duration(run: IngestionRun) {
  if (!run.started_at) return "—";
  const start = new Date(run.started_at).getTime();
  const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function ActivityPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<RunFilter>("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const runs = useAdminQuery<Paginated<IngestionRun>>(
    `/ingestion/jobs${queryString({ page, page_size: PAGE_SIZE, status: filter })}`,
  );

  async function act(run: IngestionRun, action: "cancel" | "retry") {
    setBusyId(run.id);
    try {
      await adminRequest(`/ingestion/jobs/${run.workflow_id ?? run.id}/${action}`, {
        method: "POST",
      });
      toast({
        title: action === "cancel" ? "Run cancelled" : "Run restarted",
        variant: "success",
      });
      runs.reload();
    } catch (cause) {
      toast({
        title: action === "cancel" ? "Could not cancel" : "Could not restart",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setBusyId(null);
    }
  }

  const columns = useMemo<Column<IngestionRun>[]>(
    () => [
      {
        key: "connector_key",
        label: "Source",
        render: (row) => (
          <CellTitle
            icon={<ConnectorLogo provider={row.connector_key} size="sm" />}
            subtitle={triggerLabels[row.trigger_type ?? ""] ?? "Unknown trigger"}
            title={titleCase(row.connector_key) || "Unknown source"}
          />
        ),
      },
      {
        key: "status",
        label: "Result",
        width: 150,
        render: (row) => <StatusBadge status={row.status} />,
      },
      {
        key: "started_at",
        priority: "medium",
        label: "Started",
        width: 130,
        render: (row) => (
          <span title={row.started_at}>{formatRelative(row.started_at)}</span>
        ),
      },
      {
        key: "duration",
        label: "Took",
        align: "right",
        width: 90,
        render: (row) => duration(row),
      },
      {
        key: "history_length",
        label: "Steps",
        align: "right",
        priority: "low",
        width: 80,
        render: (row) => (row.history_length ?? 0).toLocaleString(),
      },
    ],
    [],
  );

  return (
    <>
      <PageHeader
        actions={
          <Button
            icon={<RotateCw aria-hidden="true" className="h-4 w-4" />}
            onClick={runs.reload}
            variant="secondary"
          >
            Refresh
          </Button>
        }
        description="Every import run, why it started, and what it changed."
        metadata={runs.data ? pluralize(runs.data.total, "run") : undefined}
        title="Sync activity"
      />

      <ResourceList
        ariaLabel="Sync runs"
        columns={columns}
        empty={
          <EmptyState
            action={
              <Button
                icon={<Plug aria-hidden="true" className="h-4 w-4" />}
                onClick={() => router.push("/admin/connectors")}
              >
                Connect a source
              </Button>
            }
            description="Runs appear here once a connected source imports content — manually, on a schedule, or when the source pushes an update."
            icon={<Waypoints className="h-5 w-5" />}
            title="No sync runs yet"
          />
        }
        error={runs.error}
        filtersActive={Boolean(filter)}
        loading={runs.loading}
        onClearFilters={() => {
          setFilter("");
          setPage(1);
        }}
        onRetry={runs.reload}
        pagination={{
          page,
          pageSize: PAGE_SIZE,
          total: runs.data?.total ?? 0,
          onPageChange: setPage,
        }}
        rows={runs.data?.items ?? []}
        rowActions={(row) => (
          <>
            {["pending", "running"].includes(row.status) && (
              <Tooltip label="Cancel run" side="top">
                <Button
                  aria-label="Cancel this run"
                  icon={<Ban aria-hidden="true" className="h-3.5 w-3.5" />}
                  iconOnly
                  loading={busyId === row.id}
                  onClick={() => act(row, "cancel")}
                  size="sm"
                  variant="ghost"
                />
              </Tooltip>
            )}
            {["failed", "cancelled", "timed_out", "terminated"].includes(
              row.status,
            ) && (
              <Tooltip label="Run again" side="top">
                <Button
                  aria-label="Run this import again"
                  icon={<RotateCw aria-hidden="true" className="h-3.5 w-3.5" />}
                  iconOnly
                  loading={busyId === row.id}
                  onClick={() => act(row, "retry")}
                  size="sm"
                  variant="ghost"
                />
              </Tooltip>
            )}
          </>
        )}
        toolbar={
          <Segmented
            ariaLabel="Filter runs by result"
            onChange={(value) => {
              setFilter(value);
              setPage(1);
            }}
            options={filters}
            value={filter}
          />
        }
      />
    </>
  );
}
