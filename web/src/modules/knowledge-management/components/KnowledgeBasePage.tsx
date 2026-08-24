"use client";

import {
  BookOpenCheck,
  CircleAlert,
  FileText,
  Library,
  Plus,
  RefreshCw,
  SearchCheck,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { queryString, useAdminQuery } from "@/modules/admin/api";
import { KnowledgeBaseWizard } from "@/modules/knowledge-management/components/KnowledgeBaseWizard";
import { formatDate, StatusBadge } from "@/modules/knowledge-management/presentation";
import type {
  KnowledgeItem,
  Paginated,
  PluginBinding,
  SyncRun,
} from "@/modules/knowledge-management/types";

type Readiness = "search_ready" | "indexing" | "needs_attention" | "not_started";

export function KnowledgeBasePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [status, setStatus] = useState(() => searchParams.get("status") ?? "");
  const [wizardOpen, setWizardOpen] = useState(false);
  const collectionsPath = `/items${queryString({ page_size: 100, item_type: "collection", search, status })}`;
  const collections = useAdminQuery<Paginated<KnowledgeItem>>(collectionsPath);
  const documents = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=document");
  const bindings = useAdminQuery<Paginated<PluginBinding>>("/plugin-bindings?page_size=100");
  const runs = useAdminQuery<Paginated<SyncRun>>("/ingestion/jobs?page_size=100");
  const updateFilter = useCallback((key: "q" | "status", value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    router.replace(`${pathname}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  }, [pathname, router, searchParams]);
  const reloadAll = useCallback(() => {
    collections.reload();
    documents.reload();
    bindings.reload();
    runs.reload();
  }, [bindings, collections, documents, runs]);

  const records = useMemo(() => (collections.data?.items ?? []).map((collection) => {
    const collectionBindings = (bindings.data?.items ?? []).filter((binding) => binding.target_item_id === collection.id);
    const bindingIds = new Set(collectionBindings.map((binding) => binding.id));
    const collectionRuns = (runs.data?.items ?? []).filter((run) => bindingIds.has(run.binding_id));
    const collectionDocuments = (documents.data?.items ?? []).filter((document) => document.parent_item_id === collection.id);
    return {
      ...collection,
      sourceCount: collectionBindings.length,
      documentCount: collectionDocuments.length,
      readiness: readiness(collectionBindings, collectionDocuments, collectionRuns),
      schedule: scheduleLabel(collectionBindings),
    };
  }), [bindings.data?.items, collections.data?.items, documents.data?.items, runs.data?.items]);

  const counts = useMemo(() => ({
    total: records.length,
    ready: records.filter((record) => record.readiness === "search_ready").length,
    processing: records.filter((record) => record.readiness === "indexing").length,
    attention: records.filter((record) => record.readiness === "needs_attention").length,
  }), [records]);

  const columns = useMemo<Column<typeof records[number]>[]>(() => [
    {
      key: "title",
      label: "Knowledge base",
      minWidth: 260,
      sortable: true,
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--text)]">{row.title}</p>
          <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">{typeof row.metadata?.description === "string" ? row.metadata.description : `Collection · ${shortId(row.id)}`}</p>
        </div>
      ),
    },
    { key: "readiness", label: "Readiness", render: (row) => <ReadinessBadge value={row.readiness} /> },
    { key: "sourceCount", label: "Sources", align: "right", sortable: true },
    { key: "documentCount", label: "Documents", align: "right", sortable: true },
    { key: "schedule", label: "Refresh", render: (row) => row.schedule },
    { key: "status", label: "Lifecycle", render: (row) => <StatusBadge status={row.status} /> },
    { key: "updated_at", label: "Updated", minWidth: 170, sortable: true, render: (row) => formatDate(row.updated_at) },
  ], []);

  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <PageHeader
        actions={(
          <>
            <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} onClick={reloadAll} variant="secondary">Refresh</Button>
            <Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setWizardOpen(true)}>New knowledge base</Button>
          </>
        )}
        description="Curate trusted enterprise knowledge from governed sources, access rules, and auditable syncs."
        metadata={collections.data ? <span>{collections.data.total.toLocaleString()} total</span> : undefined}
        title="Knowledge Bases"
      />

      <section aria-label="Knowledge base summary" className="knowledge-metrics">
        <Metric icon={<Library />} label="Total" value={counts.total} />
        <Metric icon={<SearchCheck />} label="Search-ready" tone="ready" value={counts.ready} />
        <Metric icon={<BookOpenCheck />} label="Processing" tone="processing" value={counts.processing} />
        <Metric icon={<CircleAlert />} label="Needs attention" tone="warning" value={counts.attention} />
      </section>

      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <SearchInput ariaLabel="Search knowledge bases" className="w-full sm:max-w-sm" onChange={(value) => { setSearch(value); updateFilter("q", value); }} placeholder="Search knowledge bases…" value={search} />
        <Select
          aria-label="Filter knowledge bases by lifecycle status"
          className="w-full sm:w-44"
          onChange={(event) => { setStatus(event.target.value); updateFilter("status", event.target.value); }}
          options={[
            { value: "", label: "All lifecycle states" },
            { value: "ready", label: "Ready" },
            { value: "processing", label: "Processing" },
            { value: "failed", label: "Failed" },
            { value: "pending", label: "Pending" },
          ]}
          value={status}
        />
      </div>

      {collections.loading ? (
        <div aria-busy="true" className="knowledge-table-skeleton">
          <span>Loading governed collections…</span>
        </div>
      ) : collections.error ? (
        <ErrorState actionLabel="Retry" description={collections.error} onAction={collections.reload} title="Knowledge bases are unavailable" />
      ) : records.length ? (
        <DataTable
          columns={columns}
          data={records}
          density="default"
          emptyMessage="No knowledge bases match these filters"
          onRowClick={(row) => router.push(`/admin/knowledge-bases/${row.id}`)}
        />
      ) : (
        <div className="border-y border-[var(--border)] bg-[var(--surface)]">
          <EmptyState
            action={<Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setWizardOpen(true)}>Create knowledge base</Button>}
            description="Connect a trusted source, choose scope and access, then start the first governed sync."
            icon={<FileText className="h-5 w-5" />}
            title={search || status ? "No knowledge bases match these filters" : "Create your first knowledge base"}
          />
        </div>
      )}

      {(bindings.error || documents.error || runs.error) && !collections.error && (
        <p className="mt-3 text-xs leading-5 text-[var(--warning)]" role="status">
          Some readiness details are unavailable. Collection records remain visible; refresh after the source services recover.
        </p>
      )}

      {wizardOpen && (
        <KnowledgeBaseWizard
          onClose={() => setWizardOpen(false)}
          onCreated={(knowledgeBaseId) => {
            setWizardOpen(false);
            router.push(`/admin/knowledge-bases/${knowledgeBaseId}`);
          }}
        />
      )}
    </div>
  );
}

function Metric({ icon, label, tone, value }: { icon: React.ReactNode; label: string; tone?: "ready" | "processing" | "warning"; value: number }) {
  return (
    <div className={tone ? `knowledge-metric knowledge-metric--${tone}` : "knowledge-metric"}>
      <span aria-hidden="true">{icon}</span>
      <span><strong>{value.toLocaleString()}</strong><small>{label}</small></span>
    </div>
  );
}

function ReadinessBadge({ value }: { value: Readiness }) {
  if (value === "search_ready") return <Badge dot variant="primary">Search-ready</Badge>;
  if (value === "indexing") return <Badge dot variant="info">Processing</Badge>;
  if (value === "needs_attention") return <Badge dot variant="warning">Needs attention</Badge>;
  return <Badge dot variant="default">Not started</Badge>;
}

function readiness(bindings: PluginBinding[], documents: KnowledgeItem[], runs: SyncRun[]): Readiness {
  if (runs.some((run) => run.status === "failed") || documents.some((document) => document.status === "failed")) return "needs_attention";
  if (!bindings.length && !runs.length) return "not_started";
  if (documents.length && documents.every((document) => document.status === "ready" && document.indexed)) return "search_ready";
  return "indexing";
}

function scheduleLabel(bindings: PluginBinding[]) {
  const scheduled = bindings.find((binding) => binding.schedule?.enabled)?.schedule;
  if (!scheduled) return "Manual";
  if (scheduled.cron_expression === "0 2 * * *") return "Daily · 02:00";
  if (scheduled.cron_expression === "0 2 * * 1") return "Weekly · Mon 02:00";
  return scheduled.cron_expression;
}

function shortId(value: string) {
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}
