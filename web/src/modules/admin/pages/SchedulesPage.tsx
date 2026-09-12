"use client";

import { CalendarClock, Pause, Pencil, Play, Plug, Plus, RotateCw } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { Tooltip } from "@/components/ui/Tooltip";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import type {
  IngestionRun,
  IngestionSchedule,
  IngestionSource,
  IntegrationConnection,
  KnowledgeItem,
  Paginated,
} from "@/modules/admin/collections";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import { errorMessage, formatDateTime, formatRelative, pluralize } from "@/modules/admin/format";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";

type ScheduleRow = IngestionSource & {
  schedule: IngestionSchedule;
  collectionName: string;
  connectionName: string;
  connectorKey: string;
  latestRun?: IngestionRun;
};

const DAILY = "0 2 * * *";
const WEEKLY = "0 2 * * 1";

function cadenceOf(schedule?: IngestionSchedule | null): "daily" | "weekly" | "custom" {
  if (schedule?.cron_expression === WEEKLY) return "weekly";
  if (!schedule || schedule.cron_expression === DAILY) return "daily";
  return "custom";
}

/** Cron is an implementation detail; administrators think in plain frequency. */
function frequencyLabel(schedule: IngestionSchedule) {
  const zone = schedule.timezone ?? "UTC";
  if (schedule.cron_expression === DAILY) return `Every day at 2:00 (${zone})`;
  if (schedule.cron_expression === WEEKLY) return `Every Monday at 2:00 (${zone})`;
  return `${schedule.cron_expression} (${zone})`;
}

export function SchedulesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const collectionFilter = searchParams.get("collection") ?? "";
  const { toast } = useToast();

  const [editing, setEditing] = useState<IngestionSource | "new" | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const sourcesQuery = useAdminQuery<Paginated<IngestionSource>>(
    "/ingestion-sources?page_size=100",
  );
  const collectionsQuery = useAdminQuery<Paginated<KnowledgeItem>>(
    "/items?page_size=100&item_type=collection",
  );
  const connectionsQuery = useAdminQuery<Paginated<IntegrationConnection>>(
    "/integration-connections?page_size=100",
  );
  const runsQuery = useAdminQuery<Paginated<IngestionRun>>("/ingestion/jobs?page_size=100");

  const sources = sourcesQuery.data?.items ?? [];
  const collections = collectionsQuery.data?.items ?? [];
  const connections = connectionsQuery.data?.items ?? [];

  const rows = useMemo<ScheduleRow[]>(() => {
    const collectionNames = new Map(collections.map((entry) => [entry.id, entry.title]));
    const connectionsById = new Map(connections.map((entry) => [entry.id, entry]));
    return sources.flatMap((source) => {
      if (!source.schedule) return [];
      if (collectionFilter && source.target_item_id !== collectionFilter) return [];
      const connection = connectionsById.get(source.integration_connection_id);
      return [
        {
          ...source,
          schedule: source.schedule,
          collectionName: collectionNames.get(source.target_item_id) ?? "Unknown collection",
          connectionName:
            connection?.display_name ?? source.display_name ?? "Unknown source",
          connectorKey: connection?.connector_key ?? "file",
          latestRun: (runsQuery.data?.items ?? []).find(
            (run) => run.source_id === source.id,
          ),
        },
      ];
    });
  }, [collectionFilter, collections, connections, runsQuery.data?.items, sources]);

  const schedulable = sources.filter(
    (source) =>
      !source.schedule &&
      source.status === "active" &&
      (!collectionFilter || source.target_item_id === collectionFilter),
  );

  const loading =
    sourcesQuery.loading ||
    collectionsQuery.loading ||
    connectionsQuery.loading ||
    runsQuery.loading;
  const error =
    sourcesQuery.error ??
    collectionsQuery.error ??
    connectionsQuery.error ??
    runsQuery.error;

  async function togglePause(row: ScheduleRow) {
    setPending(row.id);
    try {
      await adminRequest(`/ingestion-sources/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          schedule: {
            schedule_type: row.schedule.schedule_type,
            cron_expression: row.schedule.cron_expression,
            timezone: row.schedule.timezone,
            enabled: !row.schedule.enabled,
            overlap_policy: row.schedule.overlap_policy,
          },
        }),
      });
      toast({
        title: row.schedule.enabled ? "Schedule paused" : "Schedule resumed",
        variant: "success",
      });
      sourcesQuery.reload();
    } catch (cause) {
      toast({
        title: "Schedule could not be changed",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setPending(null);
    }
  }

  async function runNow(row: ScheduleRow) {
    setPending(row.id);
    try {
      await adminRequest(`/ingestion-sources/${row.id}/ingest`, { method: "POST" });
      toast({
        title: "Import started",
        description: `${row.connectionName} is importing into ${row.collectionName}.`,
        variant: "success",
      });
      runsQuery.reload();
    } catch (cause) {
      toast({
        title: "Import could not start",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setPending(null);
    }
  }

  const columns = useMemo<Column<ScheduleRow>[]>(
    () => [
      {
        key: "connectionName",
        label: "Imports",
        sortable: true,
        render: (row) => (
          <CellTitle
            icon={<ConnectorLogo provider={row.connectorKey} size="sm" />}
            subtitle={`into ${row.collectionName}`}
            title={row.connectionName}
          />
        ),
      },
      {
        key: "frequency",
        label: "How often",
        minWidth: 200,
        render: (row) => frequencyLabel(row.schedule),
      },
      {
        key: "nextRun",
        label: "Next",
        width: 140,
        render: (row) =>
          row.schedule.enabled ? (
            <span title={formatDateTime(row.schedule.next_run_at)}>
              {formatRelative(row.schedule.next_run_at, "Not scheduled")}
            </span>
          ) : (
            <span className="text-[var(--text-tertiary)]">Paused</span>
          ),
      },
      {
        key: "lastRun",
        label: "Last result",
        width: 150,
        render: (row) =>
          row.latestRun ? (
            <StatusBadge status={row.latestRun.status} />
          ) : (
            <Badge tone="neutral">Not run yet</Badge>
          ),
      },
    ],
    [],
  );

  const filteredCollection = collections.find((entry) => entry.id === collectionFilter);

  return (
    <>
      <PageHeader
        actions={
          /* With nothing schedulable there is no useful primary action here —
             the empty state offers the real next step instead. */
          schedulable.length ? (
            <Button
              icon={<Plus aria-hidden="true" className="h-4 w-4" />}
              onClick={() => setEditing("new")}
            >
              Create schedule
            </Button>
          ) : undefined
        }
        description="Decide how often each connected source re-imports. Everything here runs on its own, and you can pause it at any time."
        metadata={
          filteredCollection
            ? `Filtered to ${filteredCollection.title}`
            : rows.length
              ? pluralize(rows.length, "schedule")
              : undefined
        }
        title="Schedules"
      />

      <ResourceList
        ariaLabel="Schedules"
        columns={columns}
        empty={
          <EmptyState
            action={
              schedulable.length ? (
                <Button
                  icon={<Plus aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setEditing("new")}
                >
                  Create schedule
                </Button>
              ) : (
                <Button
                  icon={<Plug aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => router.push("/admin/connectors")}
                >
                  Connect a source
                </Button>
              )
            }
            description={
              schedulable.length
                ? "Pick a source that already feeds a collection and choose how often it should re-import."
                : "Schedules keep a connected source up to date. Connect a source to a collection first, then come back."
            }
            icon={<CalendarClock className="h-5 w-5" />}
            title={
              collectionFilter
                ? "This collection has no schedules"
                : "Nothing runs automatically yet"
            }
          />
        }
        error={error}
        loading={loading}
        onRetry={() => {
          sourcesQuery.reload();
          collectionsQuery.reload();
          connectionsQuery.reload();
          runsQuery.reload();
        }}
        rows={rows}
        rowActions={(row) => (
          <>
            <Tooltip label="Import now" side="top">
              <Button
                aria-label={`Import from ${row.connectionName} now`}
                icon={<RotateCw aria-hidden="true" className="h-3.5 w-3.5" />}
                iconOnly
                loading={pending === row.id}
                onClick={() => runNow(row)}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
            <Tooltip label={row.schedule.enabled ? "Pause" : "Resume"} side="top">
              <Button
                aria-label={
                  row.schedule.enabled ? "Pause this schedule" : "Resume this schedule"
                }
                icon={
                  row.schedule.enabled ? (
                    <Pause aria-hidden="true" className="h-3.5 w-3.5" />
                  ) : (
                    <Play aria-hidden="true" className="h-3.5 w-3.5" />
                  )
                }
                iconOnly
                loading={pending === row.id}
                onClick={() => togglePause(row)}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
            <Tooltip label="Change frequency" side="top">
              <Button
                aria-label={`Edit the schedule for ${row.connectionName}`}
                icon={<Pencil aria-hidden="true" className="h-3.5 w-3.5" />}
                iconOnly
                onClick={() => setEditing(row)}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
          </>
        )}
      />

      {editing && (
        <ScheduleDialog
          collections={collections}
          connections={connections}
          existing={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            sourcesQuery.reload();
          }}
          sources={editing === "new" ? schedulable : [editing]}
        />
      )}
    </>
  );
}

function ScheduleDialog({
  collections,
  connections,
  existing,
  onClose,
  onSaved,
  sources,
}: {
  collections: KnowledgeItem[];
  connections: IntegrationConnection[];
  existing?: IngestionSource;
  onClose: () => void;
  onSaved: () => void;
  sources: IngestionSource[];
}) {
  const { toast } = useToast();
  const [sourceId, setSourceId] = useState(
    existing?.id ?? (sources.length === 1 ? sources[0].id : ""),
  );
  const [cadence, setCadence] = useState(() => cadenceOf(existing?.schedule));
  const [cron, setCron] = useState(existing?.schedule?.cron_expression ?? DAILY);
  const [timezone, setTimezone] = useState(
    existing?.schedule?.timezone ??
      Intl.DateTimeFormat().resolvedOptions().timeZone ??
      "UTC",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const source = sources.find((entry) => entry.id === sourceId);
    if (!source || saving) return;
    const expression =
      cadence === "daily" ? DAILY : cadence === "weekly" ? WEEKLY : cron.trim();
    if (!expression) {
      setError("Enter a schedule expression.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adminRequest(`/ingestion-sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          schedule: {
            schedule_type: "cron",
            cron_expression: expression,
            timezone: timezone.trim() || "UTC",
            enabled: existing?.schedule?.enabled ?? true,
            overlap_policy: existing?.schedule?.overlap_policy ?? "skip",
          },
        }),
      });
      toast({
        title: existing ? "Schedule updated" : "Schedule created",
        variant: "success",
      });
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause, "The schedule could not be saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      className="max-w-lg"
      footer={
        <>
          <Button disabled={saving} onClick={onClose} variant="secondary">
            Cancel
          </Button>
          <Button
            disabled={!sourceId}
            form="schedule-form"
            loading={saving}
            type="submit"
          >
            {existing ? "Save schedule" : "Create schedule"}
          </Button>
        </>
      }
      onClose={() => {
        if (!saving) onClose();
      }}
      open
      title={existing ? "Change frequency" : "Create schedule"}
    >
      <form className="space-y-4" id="schedule-form" onSubmit={save}>
        <p className="text-[0.8125rem] leading-5 text-[var(--text-tertiary)]">
          A schedule re-imports a connected source so its collection stays current.
        </p>
        {error && <ErrorState description={error} layout="inline" />}
        <FormField htmlFor="schedule-source" label="What to import" required>
          <Select
            disabled={Boolean(existing)}
            id="schedule-source"
            onChange={(event) => setSourceId(event.target.value)}
            options={[
              { value: "", label: "Choose a source" },
              ...sources.map((source) => ({
                value: source.id,
                label: `${
                  connections.find(
                    (connection) => connection.id === source.integration_connection_id,
                  )?.display_name ??
                  source.display_name ??
                  "Source"
                } → ${
                  collections.find((entry) => entry.id === source.target_item_id)
                    ?.title ?? "Collection"
                }`,
              })),
            ]}
            value={sourceId}
          />
        </FormField>
        <FormField htmlFor="schedule-frequency" label="How often" required>
          <Select
            id="schedule-frequency"
            onChange={(event) =>
              setCadence(event.target.value as "daily" | "weekly" | "custom")
            }
            options={[
              { value: "daily", label: "Every day at 2:00" },
              { value: "weekly", label: "Every Monday at 2:00" },
              { value: "custom", label: "A custom schedule" },
            ]}
            value={cadence}
          />
        </FormField>
        {cadence === "custom" && (
          <FormField
            helperText="Cron syntax — minute, hour, day of month, month, day of week. For example 0 6 * * 1-5 runs at 6:00 on weekdays."
            htmlFor="schedule-cron"
            label="Custom schedule"
            required
          >
            <Input
              autoComplete="off"
              id="schedule-cron"
              onChange={(event) => setCron(event.target.value)}
              value={cron}
            />
          </FormField>
        )}
        <FormField
          helperText="Times above are interpreted in this timezone."
          htmlFor="schedule-timezone"
          label="Timezone"
          required
        >
          <Input
            autoComplete="off"
            id="schedule-timezone"
            onChange={(event) => setTimezone(event.target.value)}
            value={timezone}
          />
        </FormField>
      </form>
    </Dialog>
  );
}
