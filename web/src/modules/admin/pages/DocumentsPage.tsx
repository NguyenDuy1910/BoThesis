"use client";

import { FileText, RotateCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { DocumentStatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { Tooltip } from "@/components/ui/Tooltip";
import {
  adminRequest,
  queryString,
  retryCollectionDocument,
  useAdminQuery,
} from "@/modules/admin/api";
import type { KnowledgeItem, Paginated } from "@/modules/admin/collections";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import {
  errorMessage,
  fileKind,
  formatBytes,
  formatRelative,
  pluralize,
} from "@/modules/admin/format";

const PAGE_SIZE = 25;

const statusFilters = [
  { value: "", label: "Any status" },
  { value: "ready", label: "Searchable" },
  { value: "processing", label: "Processing" },
  { value: "pending", label: "Queued" },
  { value: "failed", label: "Failed" },
  { value: "unsupported", label: "Unsupported" },
];

export function DocumentsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [status, setStatus] = useState(() => searchParams.get("status") ?? "");
  const [collectionId, setCollectionId] = useState(
    () => searchParams.get("collection") ?? "",
  );
  const [busyId, setBusyId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<KnowledgeItem | null>(null);

  const documents = useAdminQuery<Paginated<KnowledgeItem>>(
    `/items${queryString({
      page,
      page_size: PAGE_SIZE,
      item_type: "document",
      search,
      status,
      parent_item_id: collectionId || undefined,
    })}`,
  );
  const collections = useAdminQuery<Paginated<KnowledgeItem>>(
    "/items?item_type=collection&page_size=100",
  );

  const collectionsById = useMemo(
    () =>
      new Map((collections.data?.items ?? []).map((entry) => [entry.id, entry.title])),
    [collections.data?.items],
  );

  const syncFilter = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set(key, value);
      else params.delete(key);
      router.replace(`${pathname}${params.size ? `?${params}` : ""}`, {
        scroll: false,
      });
    },
    [pathname, router, searchParams],
  );

  async function retry(document: KnowledgeItem) {
    setBusyId(document.id);
    try {
      await retryCollectionDocument(document.id);
      toast({
        title: "Indexing restarted",
        description: `${document.title} is being processed again.`,
        variant: "success",
      });
      documents.reload();
    } catch (cause) {
      toast({
        title: "Could not restart indexing",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setBusyId(null);
    }
  }

  async function remove() {
    if (!removing) return;
    try {
      await adminRequest(`/items/${removing.id}`, { method: "DELETE" });
      toast({
        title: `${removing.title} removed`,
        description: "It no longer appears in assistant answers.",
        variant: "success",
      });
      setRemoving(null);
      documents.reload();
    } catch (cause) {
      throw new Error(errorMessage(cause, "The document could not be removed."));
    }
  }

  const columns = useMemo<Column<KnowledgeItem>[]>(
    () => [
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
        key: "parent_item_id",
        priority: "medium",
        label: "Collection",
        minWidth: 160,
        render: (row) =>
          row.parent_item_id ? (
            <Link
              className="text-[var(--text-secondary)] underline-offset-4 hover:text-[var(--brand-accent)] hover:underline"
              href={`/admin/collections/${row.parent_item_id}`}
              onClick={(event) => event.stopPropagation()}
            >
              {collectionsById.get(row.parent_item_id) ?? "Unknown collection"}
            </Link>
          ) : (
            <span className="text-[var(--text-muted)]">Not in a collection</span>
          ),
      },
      {
        key: "source",
        label: "Added by",
        priority: "low",
        minWidth: 140,
        render: (row) =>
          row.external_resources?.[0]?.integration_connection?.display_name ??
          "Direct upload",
      },
      {
        key: "status",
        label: "Status",
        width: 160,
        render: (row) => (
          <DocumentStatusBadge indexed={row.indexed} status={row.status} />
        ),
      },
      {
        key: "updated_at",
        priority: "medium",
        label: "Updated",
        width: 120,
        sortable: true,
        render: (row) => (
          <span title={row.updated_at}>{formatRelative(row.updated_at)}</span>
        ),
      },
    ],
    [collectionsById],
  );

  const filtersActive = Boolean(search || status || collectionId);

  return (
    <>
      <PageHeader
        description="Every file across your collections, with what is searchable and what needs a retry."
        metadata={documents.data ? pluralize(documents.data.total, "document") : undefined}
        title="Documents"
      />

      <ResourceList
        ariaLabel="Documents"
        columns={columns}
        empty={
          <EmptyState
            action={
              <Button
                icon={<Upload aria-hidden="true" className="h-4 w-4" />}
                onClick={() => router.push("/admin/collections")}
              >
                Go to collections
              </Button>
            }
            description="Documents appear here once you upload files to a collection or connect a source that imports them."
            icon={<FileText className="h-5 w-5" />}
            title="No documents yet"
          />
        }
        error={documents.error}
        filtersActive={filtersActive}
        loading={documents.loading}
        onClearFilters={() => {
          setSearch("");
          setStatus("");
          setCollectionId("");
          setPage(1);
          router.replace(pathname, { scroll: false });
        }}
        onRetry={documents.reload}
        pagination={{
          page,
          pageSize: PAGE_SIZE,
          total: documents.data?.total ?? 0,
          onPageChange: setPage,
        }}
        rows={documents.data?.items ?? []}
        rowActions={(row) => (
          <>
            {(row.status === "failed" || row.status === "unsupported") && (
              <Tooltip label="Retry indexing" side="top">
                <Button
                  aria-label={`Retry indexing ${row.title}`}
                  icon={<RotateCw aria-hidden="true" className="h-3.5 w-3.5" />}
                  iconOnly
                  loading={busyId === row.id}
                  onClick={() => retry(row)}
                  size="sm"
                  variant="ghost"
                />
              </Tooltip>
            )}
            <Tooltip label="Remove document" side="top">
              <Button
                aria-label={`Remove ${row.title}`}
                icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />}
                iconOnly
                onClick={() => setRemoving(row)}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
          </>
        )}
        toolbar={
          <>
            <SearchInput
              ariaLabel="Search documents"
              className="w-full sm:w-72"
              onChange={(value) => {
                setSearch(value);
                setPage(1);
                syncFilter("q", value);
              }}
              placeholder="Search by file name…"
              value={search}
            />
            <div className="adm-toolbar__spacer" />
            <Select
              aria-label="Filter by collection"
              className="w-full sm:w-52"
              onChange={(event) => {
                setCollectionId(event.target.value);
                setPage(1);
                syncFilter("collection", event.target.value);
              }}
              options={[
                { value: "", label: "All collections" },
                ...(collections.data?.items ?? []).map((entry) => ({
                  value: entry.id,
                  label: entry.title,
                })),
              ]}
              value={collectionId}
            />
            <Select
              aria-label="Filter by status"
              className="w-full sm:w-44"
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
                syncFilter("status", event.target.value);
              }}
              options={statusFilters}
              value={status}
            />
          </>
        }
      />

      <ConfirmDialog
        confirmLabel="Remove document"
        description={
          <>
            <strong className="font-semibold text-[var(--text)]">
              {removing?.title}
            </strong>{" "}
            will stop appearing in search and in assistant answers. If it came from
            a connected source, the next sync may bring it back.
          </>
        }
        onClose={() => setRemoving(null)}
        onConfirm={remove}
        open={Boolean(removing)}
        title="Remove this document?"
      />
    </>
  );
}
