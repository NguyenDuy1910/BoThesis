"use client";

import {
  Archive,
  Edit3,
  Library,
  LockKeyhole,
  MoreHorizontal,
  Plus,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, queryString, useAdminQuery } from "@/modules/admin/api";
import { KnowledgeBaseCreateDialog } from "@/modules/knowledge-management/components/KnowledgeBaseCreateDialog";
import {
  collectionDescription,
  KnowledgeBaseEditDialog,
} from "@/modules/knowledge-management/components/KnowledgeBaseEditDialog";
import { errorMessage, formatDate } from "@/modules/knowledge-management/presentation";
import type {
  DirectoryUser,
  KnowledgeItem,
  Paginated,
  IngestionSource,
} from "@/modules/knowledge-management/types";

type SortOption = "updated_desc" | "updated_asc" | "name_asc";
type KnowledgeBaseRecord = KnowledgeItem & {
  documentCount: number;
  sourceCount: number;
  ownerName: string;
};

export function KnowledgeBasePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [owner, setOwner] = useState(() => searchParams.get("owner") ?? "");
  const [sort, setSort] = useState<SortOption>(() => sortOption(searchParams.get("sort")));
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeItem | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeItem | null>(null);
  const [deletingNow, setDeletingNow] = useState(false);
  const backendSort = sort === "name_asc"
    ? { sort: "title", direction: "asc" }
    : { sort: "updated_at", direction: sort === "updated_asc" ? "asc" : "desc" };
  const collections = useAdminQuery<Paginated<KnowledgeItem>>(
    `/items${queryString({
      page_size: 100,
      item_type: "collection",
      search,
      created_by_user_id: owner || undefined,
      ...backendSort,
    })}`,
  );
  const documents = useAdminQuery<Paginated<KnowledgeItem>>("/items?page_size=100&item_type=document");
  const sources = useAdminQuery<Paginated<IngestionSource>>("/ingestion-sources?page_size=100");
  const users = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100&status=active");

  const updateFilter = useCallback((key: "q" | "owner" | "sort", value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value && !(key === "sort" && value === "updated_desc")) params.set(key, value);
    else params.delete(key);
    router.replace(`${pathname}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  }, [pathname, router, searchParams]);
  const handleSearch = useCallback((value: string) => {
    setSearch(value);
    updateFilter("q", value);
  }, [updateFilter]);

  const records = useMemo<KnowledgeBaseRecord[]>(() => {
    const people = new Map((users.data?.items ?? []).map((user) => [user.id, user]));
    return (collections.data?.items ?? []).map((collection) => {
      const creator = collection.created_by_user_id
        ? people.get(collection.created_by_user_id)
        : undefined;
      return {
        ...collection,
        documentCount: collection.item_count ?? (documents.data?.items ?? []).filter((document) => document.parent_item_id === collection.id).length,
        sourceCount: collection.source_count ?? (sources.data?.items ?? []).filter((source) => source.target_item_id === collection.id).length,
        ownerName: creator?.display_name || creator?.email || "Workspace owner",
      };
    }).filter((collection) => !owner || collection.created_by_user_id === owner);
  }, [sources.data?.items, collections.data?.items, documents.data?.items, owner, users.data?.items]);

  const ownerOptions = useMemo(() => [
    { value: "", label: "All owners" },
    ...(users.data?.items ?? []).map((user) => ({
      value: user.id,
      label: user.display_name || user.email,
    })),
  ], [users.data?.items]);

  const columns = useMemo<Column<KnowledgeBaseRecord>[]>(() => [
    {
      key: "title",
      label: "Knowledge base",
      minWidth: 300,
      sortable: true,
      render: (row) => (
        <div className="min-w-0 py-0.5">
          <p className="truncate font-medium text-[var(--text)]">{row.title}</p>
          <p className="mt-0.5 max-w-xl truncate text-xs text-[var(--text-muted)]">
            {collectionDescription(row) || "No description"}
          </p>
        </div>
      ),
    },
    { key: "documentCount", label: "Items", align: "right", sortable: true },
    { key: "sourceCount", label: "Sources", align: "right", sortable: true },
    { key: "ownerName", label: "Owner", minWidth: 170, sortable: true },
    { key: "updated_at", label: "Updated", minWidth: 170, sortable: true, render: (row) => formatDate(row.updated_at) },
  ], []);

  async function removeKnowledgeBase() {
    if (!deleting || deletingNow) return;
    setDeletingNow(true);
    try {
      await adminRequest(`/items/${deleting.id}`, { method: "DELETE" });
      toast({
        title: "Knowledge base archived",
        description: "The collection is hidden from normal reads; its lineage remains retained.",
        variant: "success",
      });
      setDeleting(null);
      collections.reload();
    } catch (cause) {
      toast({ title: "Knowledge base could not be archived", description: errorMessage(cause), variant: "error" });
    } finally {
      setDeletingNow(false);
    }
  }

  const filtersActive = Boolean(search || owner || sort !== "updated_desc");

  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <PageHeader
        actions={<Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>Create knowledge base</Button>}
        description="Organize trusted company knowledge into collections, then add content in the way that fits each team."
        metadata={collections.data ? <span>{collections.data.total.toLocaleString()} total</span> : undefined}
        title="Knowledge Bases"
      />

      <div className="knowledge-list-toolbar">
        <SearchInput
          ariaLabel="Search knowledge bases"
          className="w-full md:max-w-md"
          onChange={handleSearch}
          placeholder="Search by name or description…"
          value={search}
        />
        <div className="grid grid-cols-2 gap-2 sm:flex">
          <Select
            aria-label="Filter knowledge bases by owner"
            className="min-w-0 sm:w-48"
            onChange={(event) => {
              setOwner(event.target.value);
              updateFilter("owner", event.target.value);
            }}
            options={ownerOptions}
            value={owner}
          />
          <Select
            aria-label="Sort knowledge bases"
            className="min-w-0 sm:w-48"
            onChange={(event) => {
              const next = event.target.value as SortOption;
              setSort(next);
              updateFilter("sort", next);
            }}
            options={[
              { value: "updated_desc", label: "Recently updated" },
              { value: "updated_asc", label: "Least recently updated" },
              { value: "name_asc", label: "Name A–Z" },
            ]}
            value={sort}
          />
        </div>
      </div>

      {collections.loading ? (
        <KnowledgeBaseListSkeleton />
      ) : collections.error ? (
        <ErrorState actionLabel="Retry" description={collections.error} onAction={collections.reload} title="Knowledge bases are unavailable" />
      ) : records.length ? (
        <>
          <DataTable
            className="max-md:hidden"
            columns={columns}
            data={records}
            onRowClick={(row) => router.push(`/admin/knowledge-bases/${row.id}`)}
            rowActions={(row) => (
              <KnowledgeBaseRowMenu
                onArchive={() => setDeleting(row)}
                onEdit={() => setEditing(row)}
                onManageAccess={() => router.push(`/admin/knowledge-bases/${row.id}?tab=settings#access`)}
                onOpen={() => router.push(`/admin/knowledge-bases/${row.id}`)}
                row={row}
              />
            )}
          />
          <div className="space-y-2 md:hidden">
            {records.map((row) => (
              <article className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3" key={row.id}>
                <div className="flex items-start gap-3">
                  <button className="min-w-0 flex-1 text-left" onClick={() => router.push(`/admin/knowledge-bases/${row.id}`)} type="button">
                    <h2 className="truncate text-sm font-semibold text-[var(--text)]">{row.title}</h2>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--text-muted)]">{collectionDescription(row) || "No description"}</p>
                  </button>
                  <KnowledgeBaseRowMenu
                    onArchive={() => setDeleting(row)}
                    onEdit={() => setEditing(row)}
                    onManageAccess={() => router.push(`/admin/knowledge-bases/${row.id}?tab=settings#access`)}
                    onOpen={() => router.push(`/admin/knowledge-bases/${row.id}`)}
                    row={row}
                  />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-[var(--border)] pt-3 text-xs">
                  <div><dt className="text-[var(--text-muted)]">Items</dt><dd className="mt-0.5 font-medium text-[var(--text)]">{row.documentCount.toLocaleString()}</dd></div>
                  <div><dt className="text-[var(--text-muted)]">Sources</dt><dd className="mt-0.5 font-medium text-[var(--text)]">{row.sourceCount.toLocaleString()}</dd></div>
                  <div><dt className="text-[var(--text-muted)]">Owner</dt><dd className="mt-0.5 truncate font-medium text-[var(--text)]">{row.ownerName}</dd></div>
                  <div><dt className="text-[var(--text-muted)]">Updated</dt><dd className="mt-0.5 font-medium text-[var(--text)]">{formatDate(row.updated_at)}</dd></div>
                </dl>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <EmptyState
            action={filtersActive ? (
              <Button onClick={() => {
                setSearch("");
                setOwner("");
                setSort("updated_desc");
                router.replace(pathname, { scroll: false });
              }} variant="secondary">Clear filters</Button>
            ) : (
              <Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>Create knowledge base</Button>
            )}
            description={filtersActive
              ? "Try a different search, owner, or sort option."
              : "Create an empty collection now, then upload files, add items, or connect a source when you are ready."}
            icon={<Library className="h-5 w-5" />}
            title={filtersActive ? "No knowledge bases match these filters" : "Create your first knowledge base"}
          />
        </div>
      )}

      {(documents.error || sources.error || users.error) && !collections.error && (
        <p className="mt-3 text-xs leading-5 text-[var(--warning-text)]" role="status">
          Some item, source, or owner details are unavailable. Knowledge bases remain openable.
        </p>
      )}

      {createOpen && (
        <KnowledgeBaseCreateDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(knowledgeBase) => {
            setCreateOpen(false);
            router.push(`/admin/knowledge-bases/${knowledgeBase.id}`);
          }}
        />
      )}
      {editing && (
        <KnowledgeBaseEditDialog
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            collections.reload();
          }}
        />
      )}
      {deleting && (
        <Dialog
          footer={(
            <>
              <Button disabled={deletingNow} onClick={() => setDeleting(null)} variant="secondary">Cancel</Button>
              <Button loading={deletingNow} onClick={removeKnowledgeBase} variant="danger">Archive knowledge base</Button>
            </>
          )}
          onClose={() => { if (!deletingNow) setDeleting(null); }}
          open
          title="Archive knowledge base?"
        >
          <p className="text-sm leading-6 text-[var(--text-muted)]">
            <strong className="font-semibold text-[var(--text)]">{deleting.title}</strong> will be hidden from normal reads. Source lineage, raw objects, provider references, and vector records remain retained under lifecycle policy.
          </p>
        </Dialog>
      )}
    </div>
  );
}

function KnowledgeBaseListSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading knowledge bases" className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)]">
      <div className="grid grid-cols-[minmax(0,2fr)_repeat(3,minmax(7rem,0.6fr))] gap-4 border-b border-[var(--border)] bg-[var(--bg-panel)] px-4 py-3 max-md:hidden">
        {["w-32", "w-12", "w-16", "w-20"].map((width, index) => <Skeleton className={`h-3 ${width}`} key={index} />)}
      </div>
      <div className="divide-y divide-[var(--border)]">
        {[0, 1, 2, 3, 4].map((index) => (
          <div className="grid min-h-16 grid-cols-[minmax(0,2fr)_repeat(3,minmax(7rem,0.6fr))] items-center gap-4 px-4 py-3 max-md:block" key={index}>
            <div className="space-y-2"><Skeleton className="h-4 w-48 max-w-full" /><Skeleton className="h-3 w-72 max-w-full" /></div>
            <Skeleton className="h-3 w-12 max-md:hidden" />
            <Skeleton className="h-3 w-24 max-md:hidden" />
            <Skeleton className="h-3 w-28 max-md:hidden" />
          </div>
        ))}
      </div>
    </div>
  );
}

function sortOption(value: string | null): SortOption {
  return value === "updated_asc" || value === "name_asc" ? value : "updated_desc";
}

function KnowledgeBaseRowMenu({
  onArchive,
  onEdit,
  onManageAccess,
  onOpen,
  row,
}: {
  onArchive: () => void;
  onEdit: () => void;
  onManageAccess: () => void;
  onOpen: () => void;
  row: KnowledgeBaseRecord;
}) {
  return (
    <Dropdown
      ariaLabel={`Actions for ${row.title}`}
      buttonClassName="h-10 w-10 px-0"
      label={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />}
      menuClassName="w-48"
      showChevron={false}
    >
      <DropdownItem onClick={onOpen}><Library aria-hidden="true" className="h-4 w-4" />Open</DropdownItem>
      <DropdownItem onClick={onEdit}><Edit3 aria-hidden="true" className="h-4 w-4" />Rename</DropdownItem>
      <DropdownItem onClick={onManageAccess}><LockKeyhole aria-hidden="true" className="h-4 w-4" />Manage access</DropdownItem>
      <DropdownItem destructive onClick={onArchive}><Archive aria-hidden="true" className="h-4 w-4" />Archive</DropdownItem>
    </Dropdown>
  );
}
