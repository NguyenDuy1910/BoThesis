"use client";

import {
  ArrowLeft,
  CircleAlert,
  FileText,
  Link2,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { LoadingState } from "@/components/ui/LoadingState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { KnowledgeLifecycle } from "@/modules/knowledge-management/components/KnowledgeLifecycle";
import { errorMessage, formatBytes, formatDate, StatusBadge, titleCase } from "@/modules/knowledge-management/presentation";
import type {
  CollectionGrant,
  DirectoryGroup,
  DirectoryUser,
  KnowledgeItem,
  Paginated,
  PluginBinding,
  PluginConnection,
  SyncRun,
} from "@/modules/knowledge-management/types";

type DetailTab = "overview" | "documents" | "sources" | "access" | "sync" | "settings";

export function KnowledgeBaseDetailPage({ knowledgeBaseId }: { knowledgeBaseId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [tab, setTab] = useState<DetailTab>(() => detailTab(searchParams.get("tab")));
  const [action, setAction] = useState<string | null>(null);
  const item = useAdminQuery<KnowledgeItem>(`/items/${knowledgeBaseId}`);
  const documentsQuery = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=document");
  const bindingsQuery = useAdminQuery<Paginated<PluginBinding>>(`/plugin-bindings?page_size=100&target_item_id=${knowledgeBaseId}`);
  const runsQuery = useAdminQuery<Paginated<SyncRun>>("/ingestion/jobs?page_size=100");
  const connectionsQuery = useAdminQuery<Paginated<PluginConnection>>("/plugin-connections?page_size=100");
  const grantsQuery = useAdminQuery<Paginated<CollectionGrant>>(`/collections/${knowledgeBaseId}/access?page_size=100`);
  const usersQuery = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100");
  const groupsQuery = useAdminQuery<Paginated<DirectoryGroup>>("/groups?page_size=100");
  const documents = useMemo(() => (documentsQuery.data?.items ?? []).filter((document) => document.parent_item_id === knowledgeBaseId), [documentsQuery.data?.items, knowledgeBaseId]);
  const bindings = bindingsQuery.data?.items ?? [];
  const bindingIds = useMemo(() => new Set(bindings.map((binding) => binding.id)), [bindings]);
  const runs = useMemo(() => (runsQuery.data?.items ?? []).filter((run) => bindingIds.has(run.binding_id)), [bindingIds, runsQuery.data?.items]);
  const connections = new Map((connectionsQuery.data?.items ?? []).map((connection) => [connection.id, connection]));
  const grants = grantsQuery.data?.items ?? [];
  const readyDocuments = documents.filter((document) => document.indexed && document.status === "ready").length;
  const searchReady = documents.length > 0 && readyDocuments === documents.length;

  const reloadOperationalData = () => {
    documentsQuery.reload();
    bindingsQuery.reload();
    runsQuery.reload();
    item.reload();
  };

  async function runSync(bindingId: string) {
    setAction(`sync:${bindingId}`);
    try {
      await adminRequest(`/plugin-bindings/${bindingId}/sync`, { method: "POST" });
      toast({ title: "Sync requested", description: "The governed run is now queued.", variant: "success" });
      runsQuery.reload();
    } catch (error) {
      toast({ title: "Could not start sync", description: errorMessage(error), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function retryDocument(documentId: string) {
    setAction(`retry:${documentId}`);
    try {
      await adminRequest(`/items/${documentId}/retry`, { method: "POST" });
      toast({ title: "Document retry requested", variant: "success" });
      documentsQuery.reload();
    } catch (error) {
      toast({ title: "Could not retry document", description: errorMessage(error), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function removeItem(target: KnowledgeItem) {
    if (!window.confirm(`Remove ${target.title}? The record and vectors will be tombstoned; source lineage is retained.`)) return;
    setAction(`remove:${target.id}`);
    try {
      await adminRequest(`/items/${target.id}`, { method: "DELETE" });
      toast({ title: `${target.item_type === "collection" ? "Knowledge base" : "Document"} removed`, description: "Durable source records remain governed by lifecycle policy.", variant: "success" });
      if (target.item_type === "collection") router.push("/admin/knowledge-bases");
      else documentsQuery.reload();
    } catch (error) {
      toast({ title: "Remove action failed", description: errorMessage(error), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  if (item.loading) return <LoadingState title="Loading knowledge base" />;
  if (item.error || !item.data) {
    return <ErrorState actionLabel="Retry" description={item.error ?? "The knowledge base response was empty."} onAction={item.reload} title="Knowledge base unavailable" />;
  }

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "documents", label: "Documents", count: documents.length },
    { id: "sources", label: "Sources", count: bindings.length },
    { id: "access", label: "Access", count: grants.length },
    { id: "sync", label: "Sync", count: runs.length },
    { id: "settings", label: "Settings" },
  ];

  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <Link className="knowledge-backlink" href="/admin/knowledge-bases"><ArrowLeft aria-hidden="true" />All knowledge bases</Link>
      <PageHeader
        actions={(
          <>
            <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} onClick={reloadOperationalData} variant="secondary">Refresh</Button>
            <Link aria-disabled={!searchReady} className={searchReady ? "knowledge-chat-link" : "knowledge-chat-link is-disabled"} href={searchReady ? `/app?collection=${knowledgeBaseId}` : "#"} onClick={(event) => { if (!searchReady) event.preventDefault(); }}>
              <MessageSquareText aria-hidden="true" />Chat with knowledge base
            </Link>
          </>
        )}
        description={typeof item.data.metadata?.description === "string" ? item.data.metadata.description : "Governed enterprise knowledge collection."}
        metadata={<><StatusBadge status={item.data.status} />{searchReady ? <Badge dot variant="primary">Search-ready</Badge> : <Badge dot variant="info">Preparing</Badge>}</>}
        title={item.data.title}
      />

      <Tabs
        activeTab={tab}
        ariaLabel="Knowledge base sections"
        idBase="knowledge-base"
        onChange={(value) => {
          const nextTab = value as DetailTab;
          setTab(nextTab);
          const params = new URLSearchParams(searchParams.toString());
          if (nextTab === "overview") params.delete("tab");
          else params.set("tab", nextTab);
          router.replace(`${pathname}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
        }}
        tabs={tabs}
      />

      <section aria-labelledby={`knowledge-base-${tab}`} className="mt-5" id={`knowledge-base-${tab}-panel`} role="tabpanel">
        {tab === "overview" && (
          <OverviewTab bindings={bindings} documents={documents} grants={grants} item={item.data} runs={runs} searchReady={searchReady} />
        )}
        {tab === "documents" && (
          <DocumentsTab action={action} documents={documents} error={documentsQuery.error} onReload={documentsQuery.reload} onRemove={removeItem} onRetry={retryDocument} />
        )}
        {tab === "sources" && (
          <SourcesTab action={action} bindings={bindings} connections={connections} error={bindingsQuery.error ?? connectionsQuery.error} onRunSync={runSync} />
        )}
        {tab === "access" && (
          <AccessTab grants={grants} groups={groupsQuery.data?.items ?? []} inheritAccess={Boolean(item.data.inherit_access)} users={usersQuery.data?.items ?? []} />
        )}
        {tab === "sync" && <SyncTab action={action} bindings={bindings} onRunSync={runSync} runs={runs} />}
        {tab === "settings" && <SettingsTab action={action} item={item.data} onRemove={removeItem} />}
      </section>
    </div>
  );
}

function OverviewTab({ bindings, documents, grants, item, runs, searchReady }: { bindings: PluginBinding[]; documents: KnowledgeItem[]; grants: CollectionGrant[]; item: KnowledgeItem; runs: SyncRun[]; searchReady: boolean }) {
  const lastRun = runs[0];
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-5">
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Readiness lifecycle</h2></CardHeader>
          <CardBody><KnowledgeLifecycle bindings={bindings} documents={documents} runs={runs} /></CardBody>
        </Card>
        {!searchReady && runs.some((run) => run.status === "completed") && !documents.length && (
          <ErrorState description="The source sync completed but discovered no supported documents. Review the saved scope and connector permissions." title="No supported content discovered" />
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Evidence label="Governed sources" value={bindings.length} />
          <Evidence label="Documents" value={documents.length} />
          <Evidence label="Indexed" value={documents.filter((document) => document.indexed).length} />
        </div>
      </div>
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Governance summary</h2></CardHeader>
        <CardBody className="space-y-4">
          <Detail label="Collection ID" value={item.id} mono />
          <Detail label="Access model" value={item.inherit_access ? "Mirror source / inherited" : `Custom · ${grants.length} grants`} />
          <Detail label="Last sync" value={formatDate(lastRun?.finished_at ?? lastRun?.created_at)} />
          <Detail label="Last sync status" value={lastRun ? titleCase(lastRun.status) : "Not started"} />
          <div className="knowledge-callout">
            <ShieldCheck aria-hidden="true" />
            <span><strong>Server enforced</strong><small>Retrieval filters tenant and collection access before results reach the agent.</small></span>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function DocumentsTab({ action, documents, error, onReload, onRemove, onRetry }: { action: string | null; documents: KnowledgeItem[]; error: string | null; onReload: () => void; onRemove: (item: KnowledgeItem) => void; onRetry: (id: string) => void }) {
  const columns: Column<KnowledgeItem>[] = [
    { key: "title", label: "Document", minWidth: 280, sortable: true, render: (row) => <div><p className="font-medium text-[var(--text)]">{row.title}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{titleCase(row.document_type ?? "document")} · {formatBytes(row.size_bytes)}</p></div> },
    { key: "source", label: "Source", render: (row) => row.origins[0]?.connection.display_name ?? "Managed upload" },
    { key: "status", label: "Processing", render: (row) => <StatusBadge status={row.status} /> },
    { key: "indexed", label: "Indexed", render: (row) => row.indexed ? "Yes" : "No" },
    { key: "updated_at", label: "Updated", render: (row) => formatDate(row.updated_at) },
  ];
  if (error) return <ErrorState actionLabel="Retry" description={error} onAction={onReload} title="Documents are unavailable" />;
  if (!documents.length) return <EmptyState description="Run a source sync to discover supported content. Direct collection uploads require the governed target-upload contract." icon={<FileText className="h-5 w-5" />} title="No documents in this knowledge base" />;
  return (
    <DataTable
      columns={columns}
      data={documents}
      rowActions={(row) => (
        <div className="flex justify-end gap-1">
          {row.status === "failed" && <Button aria-label={`Retry ${row.title}`} icon={<RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === `retry:${row.id}`} onClick={() => onRetry(row.id)} size="sm" variant="ghost">Retry</Button>}
          <Button aria-label={`Remove ${row.title}`} icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === `remove:${row.id}`} onClick={() => onRemove(row)} size="sm" variant="ghost">Remove</Button>
        </div>
      )}
    />
  );
}

function SourcesTab({ action, bindings, connections, error, onRunSync }: { action: string | null; bindings: PluginBinding[]; connections: Map<string, PluginConnection>; error: string | null; onRunSync: (id: string) => void }) {
  if (error) return <ErrorState description={error} title="Source bindings are unavailable" />;
  if (!bindings.length) return <EmptyState icon={<Link2 className="h-5 w-5" />} title="No governed sources" description="Create a new knowledge base setup to bind a validated source." />;
  return (
    <div className="space-y-3">
      {bindings.map((binding) => {
        const connection = connections.get(binding.connection_id);
        return (
          <Card key={binding.id}>
            <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <ConnectorLogo provider={connection?.plugin_key ?? "file"} size="md" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-[var(--text)]">{connection?.display_name ?? binding.display_name ?? "Source binding"}</h3><StatusBadge status={binding.status} /></div>
                <p className="mt-1 text-xs text-[var(--text-muted)]">{scopeSummary(binding)} · Last synced {formatDate(binding.last_synced_at)}</p>
              </div>
              <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} loading={action === `sync:${binding.id}`} onClick={() => onRunSync(binding.id)} variant="secondary">Run now</Button>
            </CardBody>
          </Card>
        );
      })}
    </div>
  );
}

function AccessTab({ grants, groups, inheritAccess, users }: { grants: CollectionGrant[]; groups: DirectoryGroup[]; inheritAccess: boolean; users: DirectoryUser[] }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Effective audience</h2></CardHeader>
        {grants.length ? (
          <div className="divide-y divide-[var(--border)]">
            {grants.map((grant) => {
              const name = grant.principal_type === "user"
                ? users.find((user) => user.id === grant.principal_id)?.display_name ?? users.find((user) => user.id === grant.principal_id)?.email
                : groups.find((group) => group.id === grant.principal_id)?.display_name;
              return <div className="flex items-center gap-3 px-4 py-3" key={`${grant.principal_type}:${grant.principal_id}`}><LockKeyhole aria-hidden="true" className="h-4 w-4 text-[var(--brand-accent)]" /><div className="min-w-0 flex-1"><p className="truncate font-medium text-[var(--text)]">{name ?? grant.principal_id}</p><p className="text-xs text-[var(--text-muted)]">{titleCase(grant.principal_type)} principal</p></div><Badge>{titleCase(grant.role)}</Badge></div>;
            })}
          </div>
        ) : <EmptyState size="md" title={inheritAccess ? "Source access is mirrored" : "No explicit grants"} description={inheritAccess ? "Provider lineage and inherited collection access remain authoritative." : "Add an audience before using this collection in chat."} />}
      </Card>
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Enforcement</h2></CardHeader>
        <CardBody className="space-y-3 text-sm text-[var(--text-secondary)]">
          <p>Tenant boundary</p><StatusBadge status="active" />
          <p className="pt-2">Collection inheritance</p><Badge variant={inheritAccess ? "primary" : "default"}>{inheritAccess ? "Enabled" : "Custom only"}</Badge>
          <p className="pt-2 text-xs leading-5 text-[var(--text-muted)]">Permission filters run before retrieval results or cited content reach the agent.</p>
        </CardBody>
      </Card>
    </div>
  );
}

function SyncTab({ action, bindings, onRunSync, runs }: { action: string | null; bindings: PluginBinding[]; onRunSync: (id: string) => void; runs: SyncRun[] }) {
  const columns: Column<SyncRun>[] = [
    { key: "created_at", label: "Requested", render: (row) => formatDate(row.created_at) },
    { key: "connection", label: "Source", render: (row) => row.connection.display_name },
    { key: "trigger_type", label: "Trigger", render: (row) => titleCase(row.trigger_type) },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "processed_item_count", label: "Processed", align: "right", render: (row) => `${row.processed_item_count}/${row.discovered_item_count}` },
    { key: "written_chunk_count", label: "Chunks", align: "right" },
    { key: "error_message", label: "Result", minWidth: 220, render: (row) => row.error_message ?? (row.status === "completed" ? "Completed without a reported error" : "—") },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-end gap-2">
        {bindings.map((binding) => <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} key={binding.id} loading={action === `sync:${binding.id}`} onClick={() => onRunSync(binding.id)} variant="secondary">Run {binding.display_name ?? "source"}</Button>)}
      </div>
      {runs.length ? <DataTable columns={columns} data={runs} density="dense" /> : <EmptyState icon={<RefreshCw className="h-5 w-5" />} title="No sync activity" description="Start the first governed run to populate this history." />}
    </div>
  );
}

function SettingsTab({ action, item, onRemove }: { action: string | null; item: KnowledgeItem; onRemove: (item: KnowledgeItem) => void }) {
  return (
    <div className="max-w-3xl space-y-5">
      <Card>
        <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Collection record</h2></CardHeader>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Detail label="Title" value={item.title} />
          <Detail label="Lifecycle" value={titleCase(item.status)} />
          <Detail label="Created" value={formatDate(item.created_at)} />
          <Detail label="Updated" value={formatDate(item.updated_at)} />
        </CardBody>
      </Card>
      <Card className="border-[var(--danger-border)]">
        <CardHeader><h2 className="text-sm font-semibold text-[var(--danger)]">Lifecycle removal</h2></CardHeader>
        <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1"><p className="font-medium text-[var(--text)]">Remove this knowledge base</p><p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">The collection, provider references, raw objects, and vector points are retained under tombstone lifecycle rules.</p></div>
          <Button icon={<Trash2 aria-hidden="true" className="h-4 w-4" />} loading={action === `remove:${item.id}`} onClick={() => onRemove(item)} variant="danger">Remove knowledge base</Button>
        </CardBody>
      </Card>
    </div>
  );
}

function Evidence({ label, value }: { label: string; value: number }) {
  return <div className="knowledge-evidence"><strong>{value.toLocaleString()}</strong><span>{label}</span></div>;
}

function Detail({ label, mono, value }: { label: string; mono?: boolean; value: string }) {
  return <div><dt className="text-xs font-medium text-[var(--text-muted)]">{label}</dt><dd className={`mt-1 break-words text-sm font-medium text-[var(--text)] ${mono ? "font-mono text-xs" : ""}`}>{value}</dd></div>;
}

function scopeSummary(binding: PluginBinding) {
  const included = Array.isArray(binding.config.include_scopes) ? binding.config.include_scopes.length : 0;
  const excluded = Array.isArray(binding.config.exclude_scopes) ? binding.config.exclude_scopes.length : 0;
  return binding.config.scope_mode === "all" ? "All connected content" : `${included} included · ${excluded} excluded`;
}

function detailTab(value: string | null): DetailTab {
  return ["overview", "documents", "sources", "access", "sync", "settings"].includes(value ?? "")
    ? value as DetailTab
    : "overview";
}
