"use client";

import {
  Archive,
  ArrowLeft,
  CalendarClock,
  Edit3,
  FileText,
  Link2,
  MessageSquareText,
  MoreHorizontal,
  Plug,
  RefreshCw,
  RotateCcw,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, retryCollectionDocument, useAdminQuery } from "@/modules/admin/api";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { KnowledgeBaseAccessManager, principalName } from "@/modules/knowledge-management/components/KnowledgeBaseAccessManager";
import {
  AddContentMenu,
  ConnectSourceDialog,
  DeferredContentDialog,
} from "@/modules/knowledge-management/components/KnowledgeBaseContentActions";
import { KnowledgeBaseUploadDialog } from "@/modules/knowledge-management/components/KnowledgeBaseUploadDialog";
import {
  collectionDescription,
  KnowledgeBaseEditDialog,
} from "@/modules/knowledge-management/components/KnowledgeBaseEditDialog";
import { errorMessage, formatBytes, formatDate, StatusBadge, titleCase } from "@/modules/knowledge-management/presentation";
import type {
  CollectionGrant,
  CollectionUploadResponse,
  DirectoryGroup,
  DirectoryUser,
  KnowledgeItem,
  Paginated,
  IngestionSource,
  IntegrationConnection,
  IngestionRun,
} from "@/modules/knowledge-management/types";

type DetailTab = "items" | "sources" | "activity" | "settings";

export function KnowledgeBaseDetailPage({ knowledgeBaseId }: { knowledgeBaseId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [tab, setTab] = useState<DetailTab>(() => detailTab(searchParams.get("tab")));
  const [action, setAction] = useState<string | null>(null);
  const [connectOpen, setConnectOpen] = useState(() => Boolean(searchParams.get("connect")));
  const [uploadOpen, setUploadOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState<KnowledgeItem | null>(null);
  const item = useAdminQuery<KnowledgeItem>(`/items/${knowledgeBaseId}`);
  const documentsQuery = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=document");
  const sourcesQuery = useAdminQuery<Paginated<IngestionSource>>(`/ingestion-sources?page_size=100&target_item_id=${knowledgeBaseId}`);
  const runsQuery = useAdminQuery<Paginated<IngestionRun>>("/ingestion/jobs?page_size=100");
  const connectionsQuery = useAdminQuery<Paginated<IntegrationConnection>>("/integration-connections?page_size=100");
  const grantsQuery = useAdminQuery<Paginated<CollectionGrant>>(`/collections/${knowledgeBaseId}/access?page_size=100`);
  const usersQuery = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100");
  const groupsQuery = useAdminQuery<Paginated<DirectoryGroup>>("/groups?page_size=100");
  const documents = useMemo(
    () => (documentsQuery.data?.items ?? []).filter((document) => document.parent_item_id === knowledgeBaseId),
    [documentsQuery.data?.items, knowledgeBaseId],
  );
  const sources = sourcesQuery.data?.items ?? [];
  const sourceIds = useMemo(() => new Set(sources.map((source) => source.id)), [sources]);
  const runs = useMemo(
    () => (runsQuery.data?.items ?? []).filter((run) => sourceIds.has(run.source_id)),
    [sourceIds, runsQuery.data?.items],
  );
  const connections = new Map((connectionsQuery.data?.items ?? []).map((connection) => [connection.id, connection]));
  const grants = grantsQuery.data?.items ?? [];
  const users = usersQuery.data?.items ?? [];
  const groups = groupsQuery.data?.items ?? [];
  const readyDocuments = documents.filter((document) => document.indexed && document.status === "ready").length;
  const searchReady = documents.length > 0 && readyDocuments === documents.length;

  function reloadWorkspace() {
    item.reload();
    documentsQuery.reload();
    sourcesQuery.reload();
    runsQuery.reload();
    grantsQuery.reload();
  }

  function closeConnectDialog() {
    setConnectOpen(false);
    if (!searchParams.has("connect")) return;
    const params = new URLSearchParams(searchParams.toString());
    params.delete("connect");
    router.replace(`${pathname}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  }

  async function runIngestion(sourceId: string) {
    setAction(`ingest:${sourceId}`);
    try {
      await adminRequest(`/ingestion-sources/${sourceId}/ingest`, { method: "POST" });
      toast({ title: "Import requested", description: "The source run is queued.", variant: "success" });
      runsQuery.reload();
    } catch (cause) {
      toast({ title: "Could not start import", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function retryDocument(documentId: string) {
    setAction(`retry:${documentId}`);
    try {
      const result = await retryCollectionDocument<CollectionUploadResponse>(documentId);
      if (result.ingestion_status === "failed") {
        toast({
          title: "Indexing still failed",
          description: "The original file is safe. Try again or contact an administrator.",
          variant: "error",
        });
      } else {
        toast({ title: "Document indexed", description: "It is ready for grounded retrieval.", variant: "success" });
      }
      documentsQuery.reload();
    } catch (cause) {
      toast({ title: "Could not retry indexing", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  async function archiveItem() {
    if (!removing || action) return;
    setAction(`remove:${removing.id}`);
    try {
      await adminRequest(`/items/${removing.id}`, { method: "DELETE" });
      const collection = removing.item_type === "collection";
      toast({
        title: `${collection ? "Knowledge base" : "Item"} archived`,
        description: "Normal reads exclude it; durable lineage remains retained.",
        variant: "success",
      });
      setRemoving(null);
      if (collection) router.push("/admin/knowledge-bases");
      else documentsQuery.reload();
    } catch (cause) {
      toast({ title: "Archive action failed", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  if (item.loading) return <KnowledgeBaseDetailSkeleton />;
  if (item.error || !item.data) {
    return <ErrorState actionLabel="Retry" description={item.error ?? "The knowledge base response was empty."} onAction={item.reload} title="Knowledge base unavailable" />;
  }

  const ownerGrants = grants.filter((grant) => grant.role === "owner");
  const ownerLabel = ownerGrants.length
    ? ownerGrants.slice(0, 2).map((grant) => principalName(grant, users, groups)).join(", ")
    : "Owner unavailable";
  const additionalMembers = Math.max(0, grants.length - ownerGrants.length);
  const tabs = [
    { id: "items", label: "Items", count: documents.length },
    { id: "sources", label: "Sources", count: sources.length },
    { id: "activity", label: "Activity", count: runs.length },
    { id: "settings", label: "Settings" },
  ];

  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <Link className="knowledge-backlink" href="/admin/knowledge-bases"><ArrowLeft aria-hidden="true" />Knowledge Bases</Link>
      <PageHeader
        actions={(
          <>
            <AddContentMenu
              onConnect={() => setConnectOpen(true)}
              onConnectNew={() => router.push(`/admin/sources?returnTo=${encodeURIComponent(`/admin/knowledge-bases/${knowledgeBaseId}`)}`)}
              onManual={() => setManualOpen(true)}
              onUpload={() => setUploadOpen(true)}
            />
            <Button className="max-sm:hidden" icon={<Upload aria-hidden="true" className="h-4 w-4" />} onClick={() => setUploadOpen(true)} variant="secondary">Upload files</Button>
            <Button className="max-sm:hidden" icon={<Plug aria-hidden="true" className="h-4 w-4" />} onClick={() => setConnectOpen(true)} variant="secondary">Connect source</Button>
            <Dropdown ariaLabel="Knowledge base actions" buttonClassName="h-10 w-10 px-0" label={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />} menuClassName="w-52" showChevron={false}>
              <DropdownItem onClick={() => setEditing(true)}><Edit3 aria-hidden="true" className="h-4 w-4" />Edit details</DropdownItem>
              <DropdownItem disabled={!searchReady} onClick={() => router.push(`/app?collection=${knowledgeBaseId}`)}><MessageSquareText aria-hidden="true" className="h-4 w-4" />Chat with this knowledge</DropdownItem>
              <DropdownItem onClick={() => router.push(`/admin/schedules?knowledgeBase=${knowledgeBaseId}`)}><CalendarClock aria-hidden="true" className="h-4 w-4" />View schedules</DropdownItem>
              <DropdownItem destructive onClick={() => setRemoving(item.data)}><Archive aria-hidden="true" className="h-4 w-4" />Archive</DropdownItem>
            </Dropdown>
          </>
        )}
        description={collectionDescription(item.data) || "An empty knowledge collection ready for files, authored items, or connected sources."}
        metadata={(
          <>
            <span>{ownerLabel}{additionalMembers ? ` + ${additionalMembers} member${additionalMembers === 1 ? "" : "s"}` : ""}</span>
            <span aria-hidden="true">·</span>
            <span>Updated {formatDate(item.data.updated_at)}</span>
          </>
        )}
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
          params.delete("connect");
          if (nextTab === "items") params.delete("tab");
          else params.set("tab", nextTab);
          router.replace(`${pathname}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
        }}
        tabs={tabs}
      />

      <section aria-labelledby={`knowledge-base-${tab}`} className="mt-5" id={`knowledge-base-${tab}-panel`} role="tabpanel">
        {tab === "items" && (
          <ItemsTab
            action={action}
            documents={documents}
            error={documentsQuery.error}
            onConnect={() => setConnectOpen(true)}
            onManual={() => setManualOpen(true)}
            onReload={documentsQuery.reload}
            onRemove={setRemoving}
            onRetry={retryDocument}
            onUpload={() => setUploadOpen(true)}
          />
        )}
        {tab === "sources" && (
          <SourcesTab
            action={action}
            sources={sources}
            connections={connections}
            error={sourcesQuery.error ?? connectionsQuery.error}
            onConnect={() => setConnectOpen(true)}
            onRunIngestion={runIngestion}
          />
        )}
        {tab === "activity" && <ActivityTab action={action} sources={sources} error={runsQuery.error} knowledgeBaseId={knowledgeBaseId} onReload={runsQuery.reload} onRunIngestion={runIngestion} runs={runs} />}
        {tab === "settings" && (
          <SettingsTab
            action={action}
            accessError={grantsQuery.error ?? usersQuery.error ?? groupsQuery.error}
            grants={grants}
            groups={groups}
            item={item.data}
            onAccessChanged={grantsQuery.reload}
            onEdit={() => setEditing(true)}
            onRemove={() => setRemoving(item.data)}
            users={users}
          />
        )}
      </section>

      {connectOpen && (
        <ConnectSourceDialog
          sources={sources}
          connections={connectionsQuery.data?.items ?? []}
          error={connectionsQuery.error}
          initialConnectionId={searchParams.get("connect")}
          knowledgeBaseId={knowledgeBaseId}
          knowledgeBaseTitle={item.data.title}
          loading={connectionsQuery.loading}
          onClose={closeConnectDialog}
          onConnected={() => {
            closeConnectDialog();
            reloadWorkspace();
          }}
          onReload={connectionsQuery.reload}
        />
      )}
      {uploadOpen && (
        <KnowledgeBaseUploadDialog
          knowledgeBaseId={knowledgeBaseId}
          knowledgeBaseTitle={item.data.title}
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            item.reload();
            documentsQuery.reload();
          }}
        />
      )}
      {manualOpen && <DeferredContentDialog onClose={() => setManualOpen(false)} />}
      {editing && (
        <KnowledgeBaseEditDialog
          item={item.data}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            item.reload();
          }}
        />
      )}
      {removing && (
        <Dialog
          footer={(
            <>
              <Button disabled={Boolean(action)} onClick={() => setRemoving(null)} variant="secondary">Cancel</Button>
              <Button loading={action === `remove:${removing.id}`} onClick={archiveItem} variant="danger">Archive {removing.item_type === "collection" ? "knowledge base" : "item"}</Button>
            </>
          )}
          onClose={() => { if (!action) setRemoving(null); }}
          open
          title={`Archive ${removing.item_type === "collection" ? "knowledge base" : "item"}?`}
        >
          <p className="text-sm leading-6 text-[var(--text-muted)]">
            <strong className="font-semibold text-[var(--text)]">{removing.title}</strong> will be hidden from normal reads. Its source lineage and durable records remain retained under lifecycle policy.
          </p>
        </Dialog>
      )}
    </div>
  );
}

function ItemsTab({
  action,
  documents,
  error,
  onConnect,
  onManual,
  onReload,
  onRemove,
  onRetry,
  onUpload,
}: {
  action: string | null;
  documents: KnowledgeItem[];
  error: string | null;
  onConnect: () => void;
  onManual: () => void;
  onReload: () => void;
  onRemove: (item: KnowledgeItem) => void;
  onRetry: (id: string) => void;
  onUpload: () => void;
}) {
  const columns: Column<KnowledgeItem>[] = [
    { key: "title", label: "Item", minWidth: 280, sortable: true, render: (row) => <div><p className="font-medium text-[var(--text)]">{row.title}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{titleCase(row.document_type ?? "document")} · {formatBytes(row.size_bytes)}</p></div> },
    { key: "source", label: "Source", render: (row) => row.external_resources?.[0]?.integration_connection.display_name ?? "Direct upload" },
    { key: "status", label: "Processing", render: (row) => <StatusBadge status={row.status} /> },
    { key: "indexed", label: "Searchable", render: (row) => row.indexed ? "Yes" : "No" },
    { key: "updated_at", label: "Updated", minWidth: 170, render: (row) => formatDate(row.updated_at) },
  ];
  if (error) return <ErrorState actionLabel="Retry" description={error} onAction={onReload} title="Items are unavailable" />;
  if (!documents.length) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
        <EmptyState
          action={(
            <div className="flex flex-wrap justify-center gap-2">
              <Button icon={<Upload aria-hidden="true" className="h-4 w-4" />} onClick={onUpload}>Upload files</Button>
              <Button onClick={onManual} variant="secondary">Create item</Button>
              <Button icon={<Plug aria-hidden="true" className="h-4 w-4" />} onClick={onConnect} variant="secondary">Connect source</Button>
            </div>
          )}
          className="min-h-80 px-5"
          description="Upload documents, create an item, or connect a source to start building this knowledge base."
          icon={<FileText className="h-5 w-5" />}
          title="Add your first knowledge"
        />
      </div>
    );
  }
  return (
    <DataTable
      columns={columns}
      data={documents}
      rowActions={(row) => (
        <div className="flex justify-end gap-1">
          {row.status === "failed" && <Button aria-label={`Retry ${row.title}`} icon={<RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === `retry:${row.id}`} onClick={() => onRetry(row.id)} size="sm" variant="ghost">Retry</Button>}
          <Button aria-label={`Archive ${row.title}`} icon={<Archive aria-hidden="true" className="h-3.5 w-3.5" />} onClick={() => onRemove(row)} size="sm" variant="ghost">Archive</Button>
        </div>
      )}
    />
  );
}

function SourcesTab({ action, sources, connections, error, onConnect, onRunIngestion }: { action: string | null; sources: IngestionSource[]; connections: Map<string, IntegrationConnection>; error: string | null; onConnect: () => void; onRunIngestion: (id: string) => void }) {
  if (error) return <ErrorState description={error} title="Sources are unavailable" />;
  if (!sources.length) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
        <EmptyState action={<Button icon={<Plug aria-hidden="true" className="h-4 w-4" />} onClick={onConnect}>Connect source</Button>} description="Choose an existing validated connection or connect a new source without changing this knowledge base." icon={<Link2 className="h-5 w-5" />} title="No sources connected" />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button icon={<Plug aria-hidden="true" className="h-4 w-4" />} onClick={onConnect} variant="secondary">Connect another source</Button></div>
      {sources.map((source) => {
        const connection = connections.get(source.integration_connection_id);
        return (
          <Card key={source.id}>
            <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <ConnectorLogo provider={connection?.connector_key ?? "file"} size="md" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-[var(--text)]">{connection?.display_name ?? source.display_name ?? "Ingestion source"}</h3><StatusBadge status={source.status} /></div>
                <p className="mt-1 text-xs text-[var(--text-muted)]">{scopeSummary(source)} · Last imported {formatDate(source.last_ingested_at)}</p>
              </div>
              <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} loading={action === `ingest:${source.id}`} onClick={() => onRunIngestion(source.id)} variant="secondary">Import now</Button>
            </CardBody>
          </Card>
        );
      })}
    </div>
  );
}

function ActivityTab({ action, sources, error, knowledgeBaseId, onReload, onRunIngestion, runs }: { action: string | null; sources: IngestionSource[]; error: string | null; knowledgeBaseId: string; onReload: () => void; onRunIngestion: (id: string) => void; runs: IngestionRun[] }) {
  const scheduledCount = sources.filter((source) => source.schedule).length;
  const sourceNames = new Map(sources.map((source) => [
    source.id,
    source.integration_connection.display_name || source.display_name || "Unknown source",
  ]));
  const columns: Column<IngestionRun>[] = [
    { key: "started_at", label: "Requested", minWidth: 170, render: (row) => formatDate(row.started_at) },
    { key: "source_id", label: "Source", render: (row) => sourceNames.get(row.source_id) ?? titleCase(row.connector_key || "Unknown source") },
    { key: "trigger_type", label: "Trigger", render: (row) => titleCase(row.trigger_type ?? "unknown") },
    { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "history_length", label: "Events", align: "right" },
    { key: "finished_at", label: "Finished", minWidth: 170, render: (row) => formatDate(row.finished_at) },
  ];
  if (error) return <ErrorState actionLabel="Retry" description={error} onAction={onReload} title="Activity is unavailable" />;
  return (
    <div className="space-y-4">
      <div className="knowledge-activity-toolbar">
        <p>{scheduledCount ? `Updated by ${scheduledCount} schedule${scheduledCount === 1 ? "" : "s"}.` : "No automation schedule is configured for this knowledge base."}</p>
        <div className="flex flex-wrap gap-2">
          <Link className="knowledge-secondary-link" href={`/admin/schedules?knowledgeBase=${knowledgeBaseId}`}><CalendarClock aria-hidden="true" />Manage schedules</Link>
          {sources.map((source) => <Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} key={source.id} loading={action === `ingest:${source.id}`} onClick={() => onRunIngestion(source.id)} variant="secondary">Run {source.display_name ?? "source"}</Button>)}
        </div>
      </div>
      {runs.length ? <DataTable columns={columns} data={runs} density="dense" /> : <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"><EmptyState description="Connect a source and start an import to build activity history." icon={<RefreshCw className="h-5 w-5" />} title="No import activity" /></div>}
    </div>
  );
}

function SettingsTab({ accessError, action, grants, groups, item, onAccessChanged, onEdit, onRemove, users }: { accessError: string | null; action: string | null; grants: CollectionGrant[]; groups: DirectoryGroup[]; item: KnowledgeItem; onAccessChanged: () => void; onEdit: () => void; onRemove: () => void; users: DirectoryUser[] }) {
  return (
    <div className="max-w-5xl space-y-5">
      <Card>
        <CardHeader className="flex items-center justify-between gap-3"><div><h2 className="text-sm font-semibold text-[var(--text)]">Details</h2><p className="mt-0.5 text-xs text-[var(--text-muted)]">Name and description identify this collection across search and source setup.</p></div><Button icon={<Edit3 aria-hidden="true" className="h-4 w-4" />} onClick={onEdit} variant="secondary">Edit details</Button></CardHeader>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Detail label="Name" value={item.title} />
          <Detail label="Last updated" value={formatDate(item.updated_at)} />
          <Detail label="Created" value={formatDate(item.created_at)} />
          <Detail label="Collection ID" mono value={item.id} />
        </CardBody>
      </Card>
      {accessError
        ? <ErrorState description={accessError} title="People and access are unavailable" />
        : <KnowledgeBaseAccessManager grants={grants} groups={groups} inheritAccess={Boolean(item.inherit_access)} knowledgeBaseId={item.id} onChanged={onAccessChanged} users={users} />}
      <Card className="border-[var(--danger-border)]">
        <CardHeader><h2 className="text-sm font-semibold text-[var(--danger)]">Lifecycle</h2></CardHeader>
        <CardBody className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1"><p className="font-medium text-[var(--text)]">Archive this knowledge base</p><p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">Normal reads will exclude the collection. Provider references, raw objects, lineage, and vector records remain tombstoned rather than physically deleted.</p></div>
          <Button icon={<Archive aria-hidden="true" className="h-4 w-4" />} loading={action === `remove:${item.id}`} onClick={onRemove} variant="danger">Archive knowledge base</Button>
        </CardBody>
      </Card>
    </div>
  );
}

function Detail({ label, mono, value }: { label: string; mono?: boolean; value: string }) {
  return <div><dt className="text-xs font-medium text-[var(--text-muted)]">{label}</dt><dd className={`mt-1 break-words text-sm font-medium text-[var(--text)] ${mono ? "font-mono text-xs" : ""}`}>{value}</dd></div>;
}

function scopeSummary(source: IngestionSource) {
  const included = Array.isArray(source.config.include_scopes) ? source.config.include_scopes.length : 0;
  const excluded = Array.isArray(source.config.exclude_scopes) ? source.config.exclude_scopes.length : 0;
  return source.config.scope_mode === "all" ? "Saved connection scope" : `${included} included · ${excluded} excluded`;
}

function detailTab(value: string | null): DetailTab {
  return ["items", "sources", "activity", "settings"].includes(value ?? "")
    ? value as DetailTab
    : "items";
}

function KnowledgeBaseDetailSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading knowledge base" className="mx-auto w-full max-w-[92rem] space-y-4">
      <Skeleton className="h-8 w-36" />
      <div className="space-y-3 border-b border-[var(--border)] pb-4"><Skeleton className="h-8 w-72 max-w-full" /><Skeleton className="h-4 w-[32rem] max-w-full" /><Skeleton className="h-10 w-full max-w-2xl" /></div>
      <div className="flex gap-5 border-b border-[var(--border)] pb-3">{[0, 1, 2, 3].map((value) => <Skeleton className="h-4 w-20" key={value} />)}</div>
      <Skeleton className="h-72 w-full" />
    </div>
  );
}
