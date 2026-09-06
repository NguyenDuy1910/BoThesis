"use client";

import {
  Archive,
  ArrowLeft,
  CalendarClock,
  FileText,
  Import,
  Link2,
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Plug,
  Plus,
  RotateCw,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CellTitle, type Column, DataTable } from "@/components/ui/DataTable";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { DetailSkeleton, TableSkeleton } from "@/components/ui/Skeleton";
import { DocumentStatusBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { Tooltip } from "@/components/ui/Tooltip";
import {
  adminRequest,
  retryCollectionDocument,
  useAdminQuery,
} from "@/modules/admin/api";
import {
  collectionDescription,
  type CollectionGrant,
  type DirectoryGroup,
  type DirectoryUser,
  type IngestionRun,
  type IngestionSource,
  type IntegrationConnection,
  type KnowledgeItem,
  type Paginated,
} from "@/modules/admin/collections";
import { useBreadcrumbDetail } from "@/modules/admin/breadcrumb";
import { CollectionAccessPanel } from "@/modules/admin/components/CollectionAccessPanel";
import { CollectionEditDialog } from "@/modules/admin/components/CollectionEditDialog";
import { CollectionUploadDialog } from "@/modules/admin/components/CollectionUploadDialog";
import { ConnectSourceDialog } from "@/modules/admin/components/ConnectSourceDialog";
import {
  errorMessage,
  fileKind,
  formatBytes,
  formatDateTime,
  formatRelative,
  pluralize,
  titleCase,
} from "@/modules/admin/format";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";

type DetailTab = "documents" | "sources" | "activity" | "settings";

const detailTabs: DetailTab[] = ["documents", "sources", "activity", "settings"];

function readTab(value: string | null): DetailTab {
  return detailTabs.includes(value as DetailTab) ? (value as DetailTab) : "documents";
}

function scopeSummary(source: IngestionSource) {
  const included = Array.isArray(source.config.include_scopes)
    ? source.config.include_scopes.length
    : 0;
  return source.config.scope_mode === "all" || !included
    ? "Everything the connection can see"
    : `${pluralize(included, "area")} included`;
}

export function CollectionDetailPage({ collectionId }: { collectionId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [tab, setTab] = useState<DetailTab>(() => readTab(searchParams.get("tab")));
  const [pending, setPending] = useState<string | null>(null);
  const [connectOpen, setConnectOpen] = useState(() => Boolean(searchParams.get("connect")));
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [archivingCollection, setArchivingCollection] = useState(false);
  const [removingDocument, setRemovingDocument] = useState<KnowledgeItem | null>(null);

  const collection = useAdminQuery<KnowledgeItem>(`/items/${collectionId}`);
  const documentsQuery = useAdminQuery<Paginated<KnowledgeItem>>(
    `/items?page_size=100&item_type=document&parent_item_id=${collectionId}`,
  );
  const sourcesQuery = useAdminQuery<Paginated<IngestionSource>>(
    `/ingestion-sources?page_size=100&target_item_id=${collectionId}`,
  );
  const runsQuery = useAdminQuery<Paginated<IngestionRun>>("/ingestion/jobs?page_size=100");
  const connectionsQuery = useAdminQuery<Paginated<IntegrationConnection>>(
    "/integration-connections?page_size=100",
  );
  const grantsQuery = useAdminQuery<Paginated<CollectionGrant>>(
    `/collections/${collectionId}/access?page_size=100`,
  );
  const usersQuery = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100");
  const groupsQuery = useAdminQuery<Paginated<DirectoryGroup>>("/groups?page_size=100");

  const documents = documentsQuery.data?.items ?? [];
  const sources = sourcesQuery.data?.items ?? [];
  const sourceIds = useMemo(() => new Set(sources.map((source) => source.id)), [sources]);
  const runs = useMemo(
    () => (runsQuery.data?.items ?? []).filter((run) => sourceIds.has(run.source_id)),
    [runsQuery.data?.items, sourceIds],
  );
  const connections = useMemo(
    () =>
      new Map(
        (connectionsQuery.data?.items ?? []).map((connection) => [
          connection.id,
          connection,
        ]),
      ),
    [connectionsQuery.data?.items],
  );

  useBreadcrumbDetail(collection.data?.title);

  const searchable = documents.filter(
    (document) => document.indexed && document.status === "ready",
  ).length;
  const failed = documents.filter((document) => document.status === "failed").length;

  function reloadAll() {
    collection.reload();
    documentsQuery.reload();
    sourcesQuery.reload();
    runsQuery.reload();
    grantsQuery.reload();
  }

  function changeTab(next: string) {
    const value = readTab(next);
    setTab(value);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("connect");
    if (value === "documents") params.delete("tab");
    else params.set("tab", value);
    router.replace(`${pathname}${params.size ? `?${params}` : ""}`, { scroll: false });
  }

  function closeConnect() {
    setConnectOpen(false);
    if (!searchParams.has("connect")) return;
    const params = new URLSearchParams(searchParams.toString());
    params.delete("connect");
    router.replace(`${pathname}${params.size ? `?${params}` : ""}`, { scroll: false });
  }

  async function runImport(sourceId: string) {
    setPending(`import:${sourceId}`);
    try {
      await adminRequest(`/ingestion-sources/${sourceId}/ingest`, { method: "POST" });
      toast({
        title: "Import started",
        description: "New content appears here as it is processed.",
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

  async function retryDocument(document: KnowledgeItem) {
    setPending(`retry:${document.id}`);
    try {
      const result = await retryCollectionDocument<{ ingestion_status: string }>(
        document.id,
      );
      if (result.ingestion_status === "failed") {
        toast({
          title: "Indexing failed again",
          description: "The original file is safe. It may be corrupt or unreadable.",
          variant: "error",
        });
      } else {
        toast({
          title: `${document.title} is searchable`,
          variant: "success",
        });
      }
      documentsQuery.reload();
    } catch (cause) {
      toast({
        title: "Could not retry",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setPending(null);
    }
  }

  async function removeDocument() {
    if (!removingDocument) return;
    await adminRequest(`/items/${removingDocument.id}`, { method: "DELETE" }).catch(
      (cause) => {
        throw new Error(errorMessage(cause, "The document could not be removed."));
      },
    );
    toast({ title: `${removingDocument.title} removed`, variant: "success" });
    setRemovingDocument(null);
    documentsQuery.reload();
    collection.reload();
  }

  async function archiveCollection() {
    await adminRequest(`/items/${collectionId}`, { method: "DELETE" }).catch((cause) => {
      throw new Error(errorMessage(cause, "The collection could not be archived."));
    });
    toast({ title: "Collection archived", variant: "success" });
    router.push("/admin/collections");
  }

  if (collection.loading) return <DetailSkeleton />;
  if (collection.error || !collection.data) {
    return (
      <ErrorState
        actionLabel="Try again"
        description={collection.error ?? "This collection could not be loaded."}
        onAction={collection.reload}
        title="Collection unavailable"
      />
    );
  }

  const item = collection.data;
  const grants = grantsQuery.data?.items ?? [];
  const users = usersQuery.data?.items ?? [];
  const groups = groupsQuery.data?.items ?? [];

  const documentColumns: Column<KnowledgeItem>[] = [
    {
      key: "title",
      label: "Document",
      sortable: true,
      render: (row) => (
        <CellTitle
          icon={
            <span
              aria-hidden="true"
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--adm-r-sm)] bg-[var(--adm-inset)] text-[0.5625rem] font-bold text-[var(--text-muted)] shadow-[inset_0_0_0_1px_var(--adm-hairline)]"
            >
              {fileKind(row.title, row.document_type).slice(0, 4)}
            </span>
          }
          subtitle={formatBytes(row.size_bytes)}
          title={row.title || "Untitled document"}
        />
      ),
    },
    {
      key: "source",
      label: "Added by",
      priority: "low",
      minWidth: 150,
      render: (row) =>
        row.external_resources?.[0]?.integration_connection?.display_name ??
        "Direct upload",
    },
    {
      key: "status",
      label: "Status",
      width: 170,
      render: (row) => <DocumentStatusBadge indexed={row.indexed} status={row.status} />,
    },
    {
      key: "updated_at",
      priority: "medium",
      label: "Updated",
      width: 120,
      render: (row) => (
        <span title={formatDateTime(row.updated_at)}>
          {formatRelative(row.updated_at)}
        </span>
      ),
    },
  ];

  return (
    <>
      <Link
        className="mb-3 inline-flex items-center gap-1.5 text-[0.8125rem] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        href="/admin/collections"
      >
        <ArrowLeft aria-hidden="true" className="h-3.5 w-3.5" />
        All collections
      </Link>

      <PageHeader
        actions={
          <>
            <Dropdown
              ariaLabel="Add content to this collection"
              buttonClassName="h-9 bg-[var(--primary)] px-3 text-[var(--text-on-brand)] shadow-[var(--adm-e1)] hover:bg-[var(--primary-hover)] hover:text-[var(--text-on-brand)] hover:shadow-[var(--adm-e1)]"
              label={
                <>
                  <Plus aria-hidden="true" className="h-4 w-4" />
                  Add content
                </>
              }
              menuClassName="w-60"
            >
              <DropdownItem onClick={() => setUploadOpen(true)}>
                <Upload aria-hidden="true" className="h-4 w-4" />
                Upload files
              </DropdownItem>
              <DropdownItem onClick={() => setConnectOpen(true)}>
                <Import aria-hidden="true" className="h-4 w-4" />
                Import from a source
              </DropdownItem>
              <DropdownItem
                onClick={() =>
                  router.push(
                    `/admin/connectors?returnTo=${encodeURIComponent(`/admin/collections/${collectionId}`)}`,
                  )
                }
              >
                <Plug aria-hidden="true" className="h-4 w-4" />
                Set up a new connector
              </DropdownItem>
            </Dropdown>
            <Dropdown
              ariaLabel="Collection actions"
              buttonClassName="h-9 w-9 px-0"
              label={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />}
              menuClassName="w-56"
              showChevron={false}
            >
              <DropdownItem onClick={() => setEditing(true)}>
                <Pencil aria-hidden="true" className="h-4 w-4" />
                Edit name and description
              </DropdownItem>
              <DropdownItem
                disabled={searchable === 0}
                onClick={() => router.push(`/app?collection=${collectionId}`)}
              >
                <MessageSquareText aria-hidden="true" className="h-4 w-4" />
                Ask the assistant
              </DropdownItem>
              <DropdownItem
                onClick={() => router.push(`/admin/schedules?collection=${collectionId}`)}
              >
                <CalendarClock aria-hidden="true" className="h-4 w-4" />
                Import schedules
              </DropdownItem>
              <DropdownItem destructive onClick={() => setArchivingCollection(true)}>
                <Archive aria-hidden="true" className="h-4 w-4" />
                Archive collection
              </DropdownItem>
            </Dropdown>
          </>
        }
        description={collectionDescription(item) || undefined}
        metadata={
          <>
            <span>
              {documents.length === 0
                ? "Empty"
                : failed
                  ? `${searchable} of ${documents.length} searchable`
                  : `${pluralize(documents.length, "document")} · all searchable`}
            </span>
            <span aria-hidden="true">·</span>
            <span title={formatDateTime(item.updated_at)}>
              Updated {formatRelative(item.updated_at).toLowerCase()}
            </span>
          </>
        }
        title={item.title}
      />

      {failed > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-[var(--adm-r-md)] bg-[var(--danger-soft)] px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--danger-border)]">
          <span className="text-[0.8125rem] font-medium text-[var(--danger-text)]">
            {pluralize(failed, "document")} could not be indexed and{" "}
            {failed === 1 ? "is" : "are"} not searchable.
          </span>
        </div>
      )}

      <Tabs
        activeTab={tab}
        ariaLabel="Collection sections"
        className="mb-4"
        idBase="collection"
        onChange={changeTab}
        tabs={[
          { id: "documents", label: "Documents", count: documents.length },
          { id: "sources", label: "Sources", count: sources.length },
          { id: "activity", label: "Activity", count: runs.length },
          { id: "settings", label: "Settings" },
        ]}
      />

      <section
        aria-labelledby={`collection-${tab}`}
        id={`collection-${tab}-panel`}
        role="tabpanel"
      >
        {tab === "documents" &&
          (documentsQuery.error ? (
            <ErrorState
              actionLabel="Try again"
              description={documentsQuery.error}
              onAction={documentsQuery.reload}
              title="Documents could not be loaded"
            />
          ) : (
            <Card>
              {documentsQuery.loading ? (
                <TableSkeleton />
              ) : documents.length === 0 ? (
                <EmptyState
                  action={
                    <>
                      <Button
                        icon={<Upload aria-hidden="true" className="h-4 w-4" />}
                        onClick={() => setUploadOpen(true)}
                      >
                        Upload files
                      </Button>
                      <Button
                        icon={<Import aria-hidden="true" className="h-4 w-4" />}
                        onClick={() => setConnectOpen(true)}
                        variant="secondary"
                      >
                        Import from a source
                      </Button>
                    </>
                  }
                  description="Upload files from your device, or import them from a system you have already connected. Everything you add becomes searchable for the people who can access this collection."
                  icon={<FileText className="h-5 w-5" />}
                  title="Nothing in this collection yet"
                />
              ) : (
                <DataTable
                  ariaLabel="Documents in this collection"
                  columns={documentColumns}
                  data={documents}
                  rowActions={(row) => (
                    <>
                      {(row.status === "failed" || row.status === "unsupported") && (
                        <Tooltip label="Try indexing again" side="top">
                          <Button
                            aria-label={`Retry ${row.title}`}
                            icon={<RotateCw aria-hidden="true" className="h-3.5 w-3.5" />}
                            iconOnly
                            loading={pending === `retry:${row.id}`}
                            onClick={() => retryDocument(row)}
                            size="sm"
                            variant="ghost"
                          />
                        </Tooltip>
                      )}
                      <Tooltip label="Remove from collection" side="top">
                        <Button
                          aria-label={`Remove ${row.title}`}
                          icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />}
                          iconOnly
                          onClick={() => setRemovingDocument(row)}
                          size="sm"
                          variant="ghost"
                        />
                      </Tooltip>
                    </>
                  )}
                />
              )}
            </Card>
          ))}

        {tab === "sources" &&
          (sourcesQuery.error ? (
            <ErrorState
              actionLabel="Try again"
              description={sourcesQuery.error}
              onAction={sourcesQuery.reload}
              title="Sources could not be loaded"
            />
          ) : sources.length === 0 ? (
            <Card>
              <EmptyState
                action={
                  <Button
                    icon={<Import aria-hidden="true" className="h-4 w-4" />}
                    onClick={() => setConnectOpen(true)}
                  >
                    Import from a source
                  </Button>
                }
                description="Connect a system such as Confluence and its content will flow into this collection, staying up to date as it changes there."
                icon={<Link2 className="h-5 w-5" />}
                title="No sources feeding this collection"
              />
            </Card>
          ) : (
            <div className="space-y-2.5">
              {sources.map((source) => {
                const connection = connections.get(source.integration_connection_id);
                return (
                  <Card key={source.id}>
                    <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center">
                      <ConnectorLogo
                        provider={connection?.connector_key ?? "file"}
                        size="md"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-[0.875rem] font-semibold text-[var(--text)]">
                            {connection?.display_name ??
                              source.display_name ??
                              "Connected source"}
                          </h3>
                          <StatusBadge status={source.status} />
                        </div>
                        <p className="mt-0.5 text-[0.75rem] text-[var(--text-muted)]">
                          {scopeSummary(source)} · Last imported{" "}
                          {formatRelative(source.last_ingested_at, "never").toLowerCase()}
                          {source.schedule?.enabled ? " · on a schedule" : ""}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button
                          icon={<RotateCw aria-hidden="true" className="h-4 w-4" />}
                          loading={pending === `import:${source.id}`}
                          onClick={() => runImport(source.id)}
                          variant="secondary"
                        >
                          Import now
                        </Button>
                      </div>
                    </CardBody>
                  </Card>
                );
              })}
              <div className="flex justify-end pt-1">
                <Button
                  icon={<Import aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setConnectOpen(true)}
                  variant="secondary"
                >
                  Import from another source
                </Button>
              </div>
            </div>
          ))}

        {tab === "activity" && (
          <Card>
            <CardHeader
              actions={
                <Link
                  className="inline-flex items-center gap-1.5 rounded-[var(--adm-r-sm)] px-2 py-1 text-[0.8125rem] font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                  href={`/admin/schedules?collection=${collectionId}`}
                >
                  <CalendarClock aria-hidden="true" className="h-3.5 w-3.5" />
                  Manage schedules
                </Link>
              }
              description={
                sources.filter((source) => source.schedule).length
                  ? `${pluralize(sources.filter((source) => source.schedule).length, "source")} import on a schedule.`
                  : "Nothing imports automatically into this collection yet."
              }
              title="Import history"
            />
            {runsQuery.loading ? (
              <TableSkeleton columns={4} rows={4} />
            ) : runs.length === 0 ? (
              <EmptyState
                description="Once a connected source imports content, each run is recorded here with what it changed."
                icon={<RotateCw className="h-5 w-5" />}
                size="md"
                title="No imports yet"
              />
            ) : (
              <DataTable
                ariaLabel="Import history"
                columns={[
                  {
                    key: "connector_key",
                    label: "Source",
                    render: (row) =>
                      sources.find((source) => source.id === row.source_id)
                        ?.integration_connection.display_name ??
                      titleCase(row.connector_key),
                  },
                  {
                    key: "trigger_type",
                    label: "Started",
                    priority: "low",
                    width: 140,
                    render: (row) =>
                      row.trigger_type === "scheduled"
                        ? "On a schedule"
                        : row.trigger_type === "manual"
                          ? "By a person"
                          : titleCase(row.trigger_type ?? "unknown"),
                  },
                  {
                    key: "status",
                    label: "Result",
                    width: 140,
                    render: (row) => <StatusBadge status={row.status} />,
                  },
                  {
                    key: "started_at",
                    label: "When",
                    width: 130,
                    render: (row) => (
                      <span title={formatDateTime(row.started_at)}>
                        {formatRelative(row.started_at)}
                      </span>
                    ),
                  },
                ]}
                data={runs}
              />
            )}
          </Card>
        )}

        {tab === "settings" && (
          <div className="grid gap-4">
            <Card>
              <CardHeader
                actions={
                  <Button
                    icon={<Pencil aria-hidden="true" className="h-3.5 w-3.5" />}
                    onClick={() => setEditing(true)}
                    size="sm"
                    variant="secondary"
                  >
                    Edit
                  </Button>
                }
                description="How this collection is identified when people search."
                title="Details"
              />
              <CardBody>
                <dl className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">
                      Name
                    </dt>
                    <dd className="mt-1 text-[0.875rem] text-[var(--text)]">
                      {item.title}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">
                      Created
                    </dt>
                    <dd className="mt-1 text-[0.875rem] text-[var(--text)]">
                      {formatDateTime(item.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">
                      Last changed
                    </dt>
                    <dd className="mt-1 text-[0.875rem] text-[var(--text)]">
                      {formatDateTime(item.updated_at)}
                    </dd>
                  </div>
                  <div className="sm:col-span-3">
                    <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">
                      Description
                    </dt>
                    <dd className="mt-1 text-[0.875rem] text-[var(--text-secondary)]">
                      {collectionDescription(item) || (
                        <span className="text-[var(--text-muted)]">
                          None yet — a description helps teammates pick the right
                          collection.
                        </span>
                      )}
                    </dd>
                  </div>
                </dl>
              </CardBody>
            </Card>

            {grantsQuery.error ? (
              <ErrorState
                description={grantsQuery.error}
                title="Access could not be loaded"
              />
            ) : (
              <CollectionAccessPanel
                collectionId={collectionId}
                grants={grants}
                groups={groups}
                inheritAccess={Boolean(item.inherit_access)}
                onChanged={grantsQuery.reload}
                users={users}
              />
            )}

            <Card>
              <CardHeader
                description="Archiving hides this collection from search and from assistant answers. Nothing is deleted and an administrator can restore it."
                title="Archive this collection"
              />
              <CardBody className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-[0.8125rem] text-[var(--text-muted)]">
                  {pluralize(documents.length, "document")} and{" "}
                  {pluralize(sources.length, "source")} will stop being used.
                </p>
                <Button
                  icon={<Archive aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setArchivingCollection(true)}
                  variant="danger"
                >
                  Archive collection
                </Button>
              </CardBody>
            </Card>
          </div>
        )}
      </section>

      {connectOpen && (
        <ConnectSourceDialog
          collectionId={collectionId}
          collectionTitle={item.title}
          connections={connectionsQuery.data?.items ?? []}
          error={connectionsQuery.error}
          initialConnectionId={searchParams.get("connect")}
          loading={connectionsQuery.loading}
          onClose={closeConnect}
          onConnected={() => {
            closeConnect();
            reloadAll();
          }}
          onReload={connectionsQuery.reload}
          sources={sources}
        />
      )}
      {uploadOpen && (
        <CollectionUploadDialog
          collectionId={collectionId}
          collectionTitle={item.title}
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            collection.reload();
            documentsQuery.reload();
          }}
        />
      )}
      {editing && (
        <CollectionEditDialog
          collection={item}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            collection.reload();
          }}
        />
      )}

      <ConfirmDialog
        confirmLabel="Archive collection"
        description={
          <>
            <strong className="font-semibold text-[var(--text)]">{item.title}</strong>{" "}
            and its {pluralize(documents.length, "document")} will stop appearing in
            search and in assistant answers. Nothing is deleted, and the audit history
            is kept.
          </>
        }
        onClose={() => setArchivingCollection(false)}
        onConfirm={archiveCollection}
        open={archivingCollection}
        title="Archive this collection?"
      />
      <ConfirmDialog
        confirmLabel="Remove document"
        description={
          <>
            <strong className="font-semibold text-[var(--text)]">
              {removingDocument?.title}
            </strong>{" "}
            will stop appearing in search and in assistant answers. If it came from a
            connected source, the next import may bring it back.
          </>
        }
        onClose={() => setRemovingDocument(null)}
        onConfirm={removeDocument}
        open={Boolean(removingDocument)}
        title="Remove this document?"
      />
    </>
  );
}

