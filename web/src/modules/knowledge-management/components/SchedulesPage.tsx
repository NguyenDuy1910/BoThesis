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
  PluginBinding,
  PluginConnection,
  PluginSchedule,
  SyncRun,
} from "@/modules/knowledge-management/types";

type ScheduleRecord = PluginBinding & {
  schedule: PluginSchedule;
  collectionName: string;
  sourceName: string;
  latestRun?: SyncRun;
};

export function SchedulesPage() {
  const searchParams = useSearchParams();
  const knowledgeBaseFilter = searchParams.get("knowledgeBase") ?? "";
  const { toast } = useToast();
  const [dialogBinding, setDialogBinding] = useState<PluginBinding | "new" | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const bindingsQuery = useAdminQuery<Paginated<PluginBinding>>("/plugin-bindings?page_size=100");
  const collectionsQuery = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=collection");
  const connectionsQuery = useAdminQuery<Paginated<PluginConnection>>("/plugin-connections?page_size=100");
  const runsQuery = useAdminQuery<Paginated<SyncRun>>("/ingestion/jobs?page_size=100");
  const bindings = bindingsQuery.data?.items ?? [];
  const collections = collectionsQuery.data?.items ?? [];
  const connections = connectionsQuery.data?.items ?? [];
  const records = useMemo<ScheduleRecord[]>(() => {
    const collectionNames = new Map(collections.map((collection) => [collection.id, collection.title]));
    const sourceNames = new Map(connections.map((connection) => [connection.id, connection.display_name]));
    return bindings.flatMap((binding) => {
      if (!binding.schedule || (knowledgeBaseFilter && binding.target_item_id !== knowledgeBaseFilter)) return [];
      const latestRun = (runsQuery.data?.items ?? []).find((run) => run.binding_id === binding.id);
      return [{
        ...binding,
        schedule: binding.schedule,
        collectionName: collectionNames.get(binding.target_item_id) ?? "Unknown knowledge base",
        sourceName: sourceNames.get(binding.connection_id) ?? binding.display_name ?? "Unknown source",
        latestRun,
      }];
    });
  }, [bindings, collections, connections, knowledgeBaseFilter, runsQuery.data?.items]);
  const eligibleBindings = bindings.filter((binding) => (
    !binding.schedule
    && binding.status === "active"
    && (!knowledgeBaseFilter || binding.target_item_id === knowledgeBaseFilter)
  ));
  const loading = bindingsQuery.loading || collectionsQuery.loading || connectionsQuery.loading || runsQuery.loading;
  const error = bindingsQuery.error ?? collectionsQuery.error ?? connectionsQuery.error ?? runsQuery.error;

  const columns = useMemo<Column<ScheduleRecord>[]>(() => [
    { key: "sourceName", label: "Source", minWidth: 220, sortable: true, render: (row) => <div><p className="font-medium text-[var(--text)]">{row.sourceName}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{row.display_name ?? "Source import"}</p></div> },
    { key: "collectionName", label: "Destination", minWidth: 220, sortable: true },
    { key: "schedule", label: "Frequency", minWidth: 170, render: (row) => scheduleLabel(row.schedule) },
    { key: "lastRun", label: "Last run", minWidth: 170, render: (row) => formatDate(row.schedule.last_run_at) },
    { key: "nextRun", label: "Next run", minWidth: 170, render: (row) => row.schedule.enabled ? formatDate(row.schedule.next_run_at) : "Paused" },
    { key: "status", label: "Status", render: (row) => row.latestRun ? <StatusBadge status={row.latestRun.status} /> : <Badge variant={row.schedule.enabled ? "primary" : "default"}>{row.schedule.enabled ? "Scheduled" : "Paused"}</Badge> },
  ], []);

  async function updateSchedule(binding: PluginBinding, enabled: boolean) {
    if (!binding.schedule || action) return;
    setAction(`toggle:${binding.id}`);
    try {
      await adminRequest(`/plugin-bindings/${binding.id}`, {
        method: "PATCH",
        body: JSON.stringify({ schedule: schedulePayload(binding.schedule, enabled) }),
      });
      toast({ title: enabled ? "Schedule resumed" : "Schedule paused", variant: "success" });
      bindingsQuery.reload();
    } catch (cause) {
      toast({ title: "Schedule could not be updated", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function runNow(binding: PluginBinding) {
    setAction(`run:${binding.id}`);
    try {
      await adminRequest(`/plugin-bindings/${binding.id}/sync`, { method: "POST" });
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
        actions={<Button disabled={!eligibleBindings.length} icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setDialogBinding("new")}>Create schedule</Button>}
        description="Automate source imports independently from knowledge base creation. Pause, resume, run now, and inspect execution status here."
        metadata={knowledgeBaseFilter ? <span>Filtered to one knowledge base</span> : records.length ? <span>{records.length.toLocaleString()} schedules</span> : undefined}
        title="Schedules"
      />

      {loading ? (
        <div aria-busy="true" aria-label="Loading schedules" className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
          {[0, 1, 2, 3].map((index) => <Skeleton className="h-14" key={index} />)}
        </div>
      ) : error ? (
        <ErrorState actionLabel="Retry" description={error} onAction={() => { bindingsQuery.reload(); collectionsQuery.reload(); connectionsQuery.reload(); runsQuery.reload(); }} title="Schedules are unavailable" />
      ) : records.length ? (
        <DataTable
          columns={columns}
          data={records}
          rowActions={(row) => (
            <Dropdown ariaLabel={`Actions for ${row.sourceName} schedule`} buttonClassName="min-w-32" label="Actions" menuClassName="w-44">
              <DropdownItem onClick={() => setDialogBinding(row)}><Edit3 aria-hidden="true" className="h-4 w-4" />Edit schedule</DropdownItem>
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
            action={eligibleBindings.length
              ? <Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setDialogBinding("new")}>Create schedule</Button>
              : <Link className="knowledge-secondary-link" href="/admin/sources">Go to Sources &amp; Integrations</Link>}
            description={eligibleBindings.length
              ? "Choose a connected source, its destination knowledge base, and an execution frequency."
              : "Connect a source to a knowledge base first. Scheduling stays optional and can be configured later."}
            icon={<CalendarClock className="h-5 w-5" />}
            title={knowledgeBaseFilter ? "No schedules for this knowledge base" : "No schedules yet"}
          />
        </div>
      )}

      {dialogBinding && (
        <ScheduleDialog
          bindings={dialogBinding === "new" ? eligibleBindings : [dialogBinding]}
          collections={collections}
          connections={connections}
          initialBinding={dialogBinding === "new" ? undefined : dialogBinding}
          knowledgeBaseFilter={knowledgeBaseFilter}
          onClose={() => setDialogBinding(null)}
          onSaved={() => {
            setDialogBinding(null);
            bindingsQuery.reload();
          }}
        />
      )}
    </div>
  );
}

function ScheduleDialog({ bindings, collections, connections, initialBinding, knowledgeBaseFilter, onClose, onSaved }: { bindings: PluginBinding[]; collections: KnowledgeItem[]; connections: PluginConnection[]; initialBinding?: PluginBinding; knowledgeBaseFilter: string; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast();
  const defaultBinding = initialBinding ?? bindings.find((binding) => binding.target_item_id === knowledgeBaseFilter) ?? (bindings.length === 1 ? bindings[0] : undefined);
  const [bindingId, setBindingId] = useState(defaultBinding?.id ?? "");
  const [cadence, setCadence] = useState<"daily" | "weekly" | "custom">(() => cadenceFor(initialBinding?.schedule));
  const [cronExpression, setCronExpression] = useState(initialBinding?.schedule?.cron_expression ?? "0 2 * * *");
  const [timezone, setTimezone] = useState(initialBinding?.schedule?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedBinding = bindings.find((binding) => binding.id === bindingId);
  const options = [{ value: "", label: "Choose a source and destination" }, ...bindings.map((binding) => ({
    value: binding.id,
    label: `${connections.find((connection) => connection.id === binding.connection_id)?.display_name ?? binding.display_name ?? "Source"} → ${collections.find((collection) => collection.id === binding.target_item_id)?.title ?? "Knowledge base"}`,
  }))];

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedBinding || saving) return;
    const expression = cadence === "daily" ? "0 2 * * *" : cadence === "weekly" ? "0 2 * * 1" : cronExpression.trim();
    if (!expression) {
      setError("Enter a cron expression for the custom schedule.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adminRequest(`/plugin-bindings/${selectedBinding.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          schedule: {
            schedule_type: "cron",
            cron_expression: expression,
            timezone: timezone.trim() || "UTC",
            enabled: initialBinding?.schedule?.enabled ?? true,
            overlap_policy: initialBinding?.schedule?.overlap_policy ?? "skip",
          },
        }),
      });
      toast({ title: initialBinding ? "Schedule updated" : "Schedule created", variant: "success" });
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      footer={<><Button disabled={saving} onClick={onClose} variant="secondary">Cancel</Button><Button disabled={!bindingId} form="schedule-form" loading={saving} type="submit">{initialBinding ? "Save schedule" : "Create schedule"}</Button></>}
      onClose={() => { if (!saving) onClose(); }}
      open
      title={initialBinding ? "Edit schedule" : "Create schedule"}
    >
      <form className="space-y-4" id="schedule-form" onSubmit={save}>
        <p className="text-sm leading-6 text-[var(--text-muted)]">Schedules run a connected source into its governed destination knowledge base. They do not change the collection itself.</p>
        {error && <p className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{error}</p>}
        <FormField htmlFor="schedule-binding" label="Source and destination" required>
          <Select disabled={Boolean(initialBinding)} id="schedule-binding" onChange={(event) => setBindingId(event.target.value)} options={options} value={bindingId} />
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

function cadenceFor(schedule?: PluginSchedule | null): "daily" | "weekly" | "custom" {
  if (schedule?.cron_expression === "0 2 * * 1") return "weekly";
  if (!schedule || schedule.cron_expression === "0 2 * * *") return "daily";
  return "custom";
}

function schedulePayload(schedule: PluginSchedule, enabled: boolean) {
  return {
    schedule_type: schedule.schedule_type,
    cron_expression: schedule.cron_expression,
    timezone: schedule.timezone,
    enabled,
    overlap_policy: schedule.overlap_policy,
  };
}

function scheduleLabel(schedule: PluginSchedule) {
  if (schedule.cron_expression === "0 2 * * *") return `Daily · 02:00 ${schedule.timezone ?? "UTC"}`;
  if (schedule.cron_expression === "0 2 * * 1") return `Weekly · Mon 02:00 ${schedule.timezone ?? "UTC"}`;
  return `${schedule.cron_expression} · ${schedule.timezone ?? "UTC"}`;
}
