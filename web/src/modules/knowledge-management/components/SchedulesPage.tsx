"use client";

import {
  CalendarClock,
  Edit3,
  Pause,
  Play,
  Plus,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { errorMessage, formatDate, StatusBadge } from "@/modules/knowledge-management/presentation";
import type {
  KnowledgeItem,
  Paginated,
  IngestionSource,
  IntegrationConnection,
  IngestionSchedule,
  IngestionRun,
} from "@/modules/knowledge-management/types";

type ScheduleRecord = IngestionSource & {
  schedule: IngestionSchedule;
  collectionName: string;
  sourceName: string;
  latestRun?: IngestionRun;
};

export function SchedulesPage() {
  const searchParams = useSearchParams();
  const knowledgeBaseFilter = searchParams.get("knowledgeBase") ?? "";
  const { toast } = useToast();
  const [dialogSource, setDialogSource] = useState<IngestionSource | "new" | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const sourcesQuery = useAdminQuery<Paginated<IngestionSource>>("/ingestion-sources?page_size=100");
  const collectionsQuery = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=collection");
  const connectionsQuery = useAdminQuery<Paginated<IntegrationConnection>>("/integration-connections?page_size=100");
  const runsQuery = useAdminQuery<Paginated<IngestionRun>>("/ingestion/jobs?page_size=100");
  const sources = sourcesQuery.data?.items ?? [];
  const collections = collectionsQuery.data?.items ?? [];
  const connections = connectionsQuery.data?.items ?? [];
  const records = useMemo<ScheduleRecord[]>(() => {
    const collectionNames = new Map(collections.map((collection) => [collection.id, collection.title]));
    const sourceNames = new Map(connections.map((connection) => [connection.id, connection.display_name]));
    return sources.flatMap((source) => {
      if (!source.schedule || (knowledgeBaseFilter && source.target_item_id !== knowledgeBaseFilter)) return [];
      const latestRun = (runsQuery.data?.items ?? []).find((run) => run.source_id === source.id);
      return [{
        ...source,
        schedule: source.schedule,
        collectionName: collectionNames.get(source.target_item_id) ?? "Unknown knowledge base",
        sourceName: sourceNames.get(source.integration_connection_id) ?? source.display_name ?? "Unknown source",
        latestRun,
      }];
    });
  }, [sources, collections, connections, knowledgeBaseFilter, runsQuery.data?.items]);
  const eligibleSources = sources.filter((source) => (
    !source.schedule
    && source.status === "active"
    && (!knowledgeBaseFilter || source.target_item_id === knowledgeBaseFilter)
  ));
  const loading = sourcesQuery.loading || collectionsQuery.loading || connectionsQuery.loading || runsQuery.loading;
  const error = sourcesQuery.error ?? collectionsQuery.error ?? connectionsQuery.error ?? runsQuery.error;

  const columns = useMemo<Column<ScheduleRecord>[]>(() => [
    { key: "sourceName", label: "Source", minWidth: 220, sortable: true, render: (row) => <div><p className="font-medium text-[var(--text)]">{row.sourceName}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{row.display_name ?? "Source import"}</p></div> },
    { key: "collectionName", label: "Destination", minWidth: 220, sortable: true },
    { key: "schedule", label: "Frequency", minWidth: 170, render: (row) => scheduleLabel(row.schedule) },
    { key: "lastRun", label: "Last run", minWidth: 170, render: (row) => formatDate(row.schedule.last_run_at) },
    { key: "nextRun", label: "Next run", minWidth: 170, render: (row) => row.schedule.enabled ? formatDate(row.schedule.next_run_at) : "Paused" },
    { key: "status", label: "Status", render: (row) => row.latestRun ? <StatusBadge status={row.latestRun.status} /> : <Badge variant={row.schedule.enabled ? "primary" : "default"}>{row.schedule.enabled ? "Scheduled" : "Paused"}</Badge> },
  ], []);

  async function updateSchedule(source: IngestionSource, enabled: boolean) {
    if (!source.schedule || action) return;
    setAction(`toggle:${source.id}`);
    try {
      await adminRequest(`/ingestion-sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify({ schedule: schedulePayload(source.schedule, enabled) }),
      });
      toast({ title: enabled ? "Schedule resumed" : "Schedule paused", variant: "success" });
      sourcesQuery.reload();
    } catch (cause) {
      toast({ title: "Schedule could not be updated", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function runNow(source: IngestionSource) {
    setAction(`run:${source.id}`);
    try {
      await adminRequest(`/ingestion-sources/${source.id}/ingest`, { method: "POST" });
      toast({ title: "Run requested", description: "The import is queued.", variant: "success" });
      runsQuery.reload();
    } catch (cause) {
      toast({ title: "Run could not start", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <PageHeader
        actions={<Button disabled={!eligibleSources.length} icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setDialogSource("new")}>Create schedule</Button>}
        description="Automate source imports independently from knowledge base creation. Pause, resume, run now, and inspect execution status here."
        metadata={knowledgeBaseFilter ? <span>Filtered to one knowledge base</span> : records.length ? <span>{records.length.toLocaleString()} schedules</span> : undefined}
        title="Schedules"
      />

      {loading ? (
        <div aria-busy="true" aria-label="Loading schedules" className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
          {[0, 1, 2, 3].map((index) => <Skeleton className="h-14" key={index} />)}
        </div>
      ) : error ? (
        <ErrorState actionLabel="Retry" description={error} onAction={() => { sourcesQuery.reload(); collectionsQuery.reload(); connectionsQuery.reload(); runsQuery.reload(); }} title="Schedules are unavailable" />
      ) : records.length ? (
        <DataTable
          columns={columns}
          data={records}
          rowActions={(row) => (
            <Dropdown ariaLabel={`Actions for ${row.sourceName} schedule`} buttonClassName="min-w-32" label="Actions" menuClassName="w-44">
              <DropdownItem onClick={() => setDialogSource(row)}><Edit3 aria-hidden="true" className="h-4 w-4" />Edit schedule</DropdownItem>
              <DropdownItem onClick={() => updateSchedule(row, !row.schedule.enabled)}>
                {row.schedule.enabled ? <Pause aria-hidden="true" className="h-4 w-4" /> : <Play aria-hidden="true" className="h-4 w-4" />}
                {row.schedule.enabled ? "Pause" : "Resume"}
              </DropdownItem>
              <DropdownItem onClick={() => runNow(row)}><RefreshCw aria-hidden="true" className="h-4 w-4" />Run now</DropdownItem>
            </Dropdown>
          )}
        />
      ) : (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <EmptyState
            action={eligibleSources.length
              ? <Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setDialogSource("new")}>Create schedule</Button>
              : <Link className="knowledge-secondary-link" href="/admin/sources">Go to Sources &amp; Integrations</Link>}
            description={eligibleSources.length
              ? "Choose a connected source, its destination knowledge base, and an execution frequency."
              : "Connect a source to a knowledge base first. Scheduling stays optional and can be configured later."}
            icon={<CalendarClock className="h-5 w-5" />}
            title={knowledgeBaseFilter ? "No schedules for this knowledge base" : "No schedules yet"}
          />
        </div>
      )}

      {dialogSource && (
        <ScheduleDialog
          sources={dialogSource === "new" ? eligibleSources : [dialogSource]}
          collections={collections}
          connections={connections}
          initialSource={dialogSource === "new" ? undefined : dialogSource}
          knowledgeBaseFilter={knowledgeBaseFilter}
          onClose={() => setDialogSource(null)}
          onSaved={() => {
            setDialogSource(null);
            sourcesQuery.reload();
          }}
        />
      )}
    </div>
  );
}

function ScheduleDialog({ sources, collections, connections, initialSource, knowledgeBaseFilter, onClose, onSaved }: { sources: IngestionSource[]; collections: KnowledgeItem[]; connections: IntegrationConnection[]; initialSource?: IngestionSource; knowledgeBaseFilter: string; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast();
  const defaultSource = initialSource ?? sources.find((source) => source.target_item_id === knowledgeBaseFilter) ?? (sources.length === 1 ? sources[0] : undefined);
  const [sourceId, setSourceId] = useState(defaultSource?.id ?? "");
  const [cadence, setCadence] = useState<"daily" | "weekly" | "custom">(() => cadenceFor(initialSource?.schedule));
  const [cronExpression, setCronExpression] = useState(initialSource?.schedule?.cron_expression ?? "0 2 * * *");
  const [timezone, setTimezone] = useState(initialSource?.schedule?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedSource = sources.find((source) => source.id === sourceId);
  const options = [{ value: "", label: "Choose a source and destination" }, ...sources.map((source) => ({
    value: source.id,
    label: `${connections.find((connection) => connection.id === source.integration_connection_id)?.display_name ?? source.display_name ?? "Source"} → ${collections.find((collection) => collection.id === source.target_item_id)?.title ?? "Knowledge base"}`,
  }))];

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSource || saving) return;
    const expression = cadence === "daily" ? "0 2 * * *" : cadence === "weekly" ? "0 2 * * 1" : cronExpression.trim();
    if (!expression) {
      setError("Enter a cron expression for the custom schedule.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adminRequest(`/ingestion-sources/${selectedSource.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          schedule: {
            schedule_type: "cron",
            cron_expression: expression,
            timezone: timezone.trim() || "UTC",
            enabled: initialSource?.schedule?.enabled ?? true,
            overlap_policy: initialSource?.schedule?.overlap_policy ?? "skip",
          },
        }),
      });
      toast({ title: initialSource ? "Schedule updated" : "Schedule created", variant: "success" });
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      footer={<><Button disabled={saving} onClick={onClose} variant="secondary">Cancel</Button><Button disabled={!sourceId} form="schedule-form" loading={saving} type="submit">{initialSource ? "Save schedule" : "Create schedule"}</Button></>}
      onClose={() => { if (!saving) onClose(); }}
      open
      title={initialSource ? "Edit schedule" : "Create schedule"}
    >
      <form className="space-y-4" id="schedule-form" onSubmit={save}>
        <p className="text-sm leading-6 text-[var(--text-muted)]">Schedules run a connected source into its governed destination knowledge base. They do not change the collection itself.</p>
        {error && <p className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{error}</p>}
        <FormField htmlFor="schedule-source" label="Source and destination" required>
          <Select disabled={Boolean(initialSource)} id="schedule-source" onChange={(event) => setSourceId(event.target.value)} options={options} value={sourceId} />
        </FormField>
        <FormField htmlFor="schedule-frequency" label="Frequency" required>
          <Select id="schedule-frequency" onChange={(event) => setCadence(event.target.value as "daily" | "weekly" | "custom")} options={[{ value: "daily", label: "Daily at 02:00" }, { value: "weekly", label: "Weekly on Monday at 02:00" }, { value: "custom", label: "Custom cron expression" }]} value={cadence} />
        </FormField>
        {cadence === "custom" && <FormField helperText="Five-field cron syntax, for example 0 6 * * 1-5." htmlFor="schedule-cron" label="Cron expression" required><Input aria-describedby="schedule-cron-helper" autoComplete="off" id="schedule-cron" onChange={(event) => setCronExpression(event.target.value)} value={cronExpression} /></FormField>}
        <FormField htmlFor="schedule-timezone" label="Timezone" required><Input autoComplete="off" id="schedule-timezone" onChange={(event) => setTimezone(event.target.value)} value={timezone} /></FormField>
      </form>
    </Dialog>
  );
}

function cadenceFor(schedule?: IngestionSchedule | null): "daily" | "weekly" | "custom" {
  if (schedule?.cron_expression === "0 2 * * 1") return "weekly";
  if (!schedule || schedule.cron_expression === "0 2 * * *") return "daily";
  return "custom";
}

function schedulePayload(schedule: IngestionSchedule, enabled: boolean) {
  return {
    schedule_type: schedule.schedule_type,
    cron_expression: schedule.cron_expression,
    timezone: schedule.timezone,
    enabled,
    overlap_policy: schedule.overlap_policy,
  };
}

function scheduleLabel(schedule: IngestionSchedule) {
  if (schedule.cron_expression === "0 2 * * *") return `Daily · 02:00 ${schedule.timezone ?? "UTC"}`;
  if (schedule.cron_expression === "0 2 * * 1") return `Weekly · Mon 02:00 ${schedule.timezone ?? "UTC"}`;
  return `${schedule.cron_expression} · ${schedule.timezone ?? "UTC"}`;
}
