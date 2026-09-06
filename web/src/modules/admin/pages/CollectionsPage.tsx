"use client";

import {
  Archive,
  Boxes,
  MoreHorizontal,
  Pencil,
  Plug,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { type Column, CellTitle } from "@/components/ui/DataTable";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, queryString, useAdminQuery } from "@/modules/admin/api";
import { CollectionCreateDialog } from "@/modules/admin/components/CollectionCreateDialog";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import { errorMessage, formatRelative, pluralize } from "@/modules/admin/format";
import { CollectionEditDialog } from "@/modules/admin/components/CollectionEditDialog";
import {
  collectionDescription,
  type DirectoryUser,
  type KnowledgeItem,
  type Paginated,
} from "@/modules/admin/collections";

type SortOption = "updated_desc" | "updated_asc" | "name_asc";

type CollectionRow = KnowledgeItem & {
  documentCount: number;
  sourceCount: number;
  ownerName: string;
};

const sortOptions = [
  { value: "updated_desc", label: "Recently updated" },
  { value: "updated_asc", label: "Least recently updated" },
  { value: "name_asc", label: "Name A–Z" },
];

export function CollectionsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [owner, setOwner] = useState(() => searchParams.get("owner") ?? "");
  const [sort, setSort] = useState<SortOption>(() =>
    ["updated_asc", "name_asc"].includes(searchParams.get("sort") ?? "")
      ? (searchParams.get("sort") as SortOption)
      : "updated_desc",
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeItem | null>(null);
  const [archiving, setArchiving] = useState<CollectionRow | null>(null);

  const backendSort =
    sort === "name_asc"
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
  const users = useAdminQuery<Paginated<DirectoryUser>>(
    "/users?page_size=100&status=active",
  );

  const syncFilter = useCallback(
    (key: string, value: string, isDefault: boolean) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value && !isDefault) params.set(key, value);
      else params.delete(key);
      router.replace(`${pathname}${params.size ? `?${params}` : ""}`, {
        scroll: false,
      });
    },
    [pathname, router, searchParams],
  );

  const rows = useMemo<CollectionRow[]>(() => {
    const people = new Map((users.data?.items ?? []).map((user) => [user.id, user]));
    return (collections.data?.items ?? []).map((collection) => {
      const creator = collection.created_by_user_id
        ? people.get(collection.created_by_user_id)
        : undefined;
      return {
        ...collection,
        documentCount: collection.item_count ?? 0,
        sourceCount: collection.source_count ?? 0,
        ownerName: creator?.display_name || creator?.email || "Workspace owner",
      };
    });
  }, [collections.data?.items, users.data?.items]);

  const columns = useMemo<Column<CollectionRow>[]>(
    () => [
      {
        key: "title",
        label: "Collection",
        sortable: true,
        render: (row) => (
          <CellTitle
            icon={
              <span
                aria-hidden="true"
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--adm-r-sm)] bg-[var(--brand-accent-soft)] text-[var(--brand-accent)]"
              >
                <Boxes className="h-3.5 w-3.5" />
              </span>
            }
            subtitle={collectionDescription(row) || "No description yet"}
            title={row.title}
          />
        ),
      },
      {
        key: "documentCount",
        label: "Documents",
        align: "right",
        sortable: true,
        width: 110,
        render: (row) =>
          row.documentCount ? (
            row.documentCount.toLocaleString()
          ) : (
            <span className="text-[var(--text-muted)]">Empty</span>
          ),
      },
      {
        key: "sourceCount",
        label: "Sources",
        align: "right",
        priority: "low",
        width: 90,
        render: (row) =>
          row.sourceCount ? (
            row.sourceCount.toLocaleString()
          ) : (
            <span className="text-[var(--text-muted)]">—</span>
          ),
      },
      {
        key: "ownerName",
        label: "Owner",
        priority: "low",
        minWidth: 150,
        sortable: true,
      },
      {
        key: "updated_at",
        priority: "medium",
        label: "Updated",
        minWidth: 120,
        sortable: true,
        render: (row) => (
          <span title={row.updated_at}>{formatRelative(row.updated_at)}</span>
        ),
      },
    ],
    [],
  );

  const filtersActive = Boolean(search || owner);

  async function archiveCollection() {
    if (!archiving) return;
    try {
      await adminRequest(`/items/${archiving.id}`, { method: "DELETE" });
      toast({
        title: `${archiving.title} archived`,
        description: "It no longer appears in search. Its history is kept.",
        variant: "success",
      });
      setArchiving(null);
      collections.reload();
    } catch (cause) {
      throw new Error(errorMessage(cause, "The collection could not be archived."));
    }
  }

  return (
    <>
      <PageHeader
        actions={
          <Button
            icon={<Plus aria-hidden="true" className="h-4 w-4" />}
            onClick={() => setCreateOpen(true)}
          >
            Create collection
          </Button>
        }
        description="Group related knowledge so teams and the assistant search the right material."
        metadata={
          collections.data ? pluralize(collections.data.total, "collection") : undefined
        }
        title="Collections"
      />

      <ResourceList
        ariaLabel="Collections"
        columns={columns}
        empty={
          <EmptyState
            action={
              <>
                <Button
                  icon={<Plus aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => setCreateOpen(true)}
                >
                  Create collection
                </Button>
                <Button
                  icon={<Plug aria-hidden="true" className="h-4 w-4" />}
                  onClick={() => router.push("/admin/connectors")}
                  variant="secondary"
                >
                  Browse connectors
                </Button>
              </>
            }
            description="A collection holds the documents and connected sources the assistant answers from. Start with one per team or topic."
            icon={<Boxes className="h-5 w-5" />}
            title="Create your first collection"
          />
        }
        error={collections.error}
        filtersActive={filtersActive}
        loading={collections.loading}
        onClearFilters={() => {
          setSearch("");
          setOwner("");
          router.replace(pathname, { scroll: false });
        }}
        onRetry={collections.reload}
        onRowClick={(row) => router.push(`/admin/collections/${row.id}`)}
        rows={rows}
        rowActions={(row) => (
          <Dropdown
            ariaLabel={`Actions for ${row.title}`}
            buttonClassName="h-8 w-8 bg-transparent px-0 shadow-none hover:bg-[var(--surface-hover)] hover:shadow-none"
            label={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />}
            menuClassName="w-48"
            showChevron={false}
          >
            <DropdownItem onClick={() => setEditing(row)}>
              <Pencil aria-hidden="true" className="h-4 w-4" />
              Rename
            </DropdownItem>
            <DropdownItem
              onClick={() =>
                router.push(`/admin/collections/${row.id}?tab=settings`)
              }
            >
              <ShieldCheck aria-hidden="true" className="h-4 w-4" />
              Manage access
            </DropdownItem>
            <DropdownItem destructive onClick={() => setArchiving(row)}>
              <Archive aria-hidden="true" className="h-4 w-4" />
              Archive
            </DropdownItem>
          </Dropdown>
        )}
        toolbar={
          <>
            <SearchInput
              ariaLabel="Search collections"
              className="w-full sm:w-72"
              onChange={(value) => {
                setSearch(value);
                syncFilter("q", value, false);
              }}
              placeholder="Search collections…"
              value={search}
            />
            <div className="adm-toolbar__spacer" />
            <Select
              aria-label="Filter by owner"
              className="w-full sm:w-44"
              onChange={(event) => {
                setOwner(event.target.value);
                syncFilter("owner", event.target.value, false);
              }}
              options={[
                { value: "", label: "All owners" },
                ...(users.data?.items ?? []).map((user) => ({
                  value: user.id,
                  label: user.display_name || user.email,
                })),
              ]}
              value={owner}
            />
            <Select
              aria-label="Sort collections"
              className="w-full sm:w-48"
              onChange={(event) => {
                const next = event.target.value as SortOption;
                setSort(next);
                syncFilter("sort", next, next === "updated_desc");
              }}
              options={sortOptions}
              value={sort}
            />
          </>
        }
      />

      <CollectionCreateDialog
        onClose={() => setCreateOpen(false)}
        open={createOpen}
      />
      {editing && (
        <CollectionEditDialog
          collection={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            collections.reload();
          }}
        />
      )}
      <ConfirmDialog
        confirmLabel="Archive collection"
        description={
          <>
            <strong className="font-semibold text-[var(--text)]">
              {archiving?.title}
            </strong>{" "}
            and its {pluralize(archiving?.documentCount ?? 0, "document")} will stop
            appearing in search and in assistant answers. Nothing is deleted — an
            administrator can restore it, and the audit history is kept.
          </>
        }
        onClose={() => setArchiving(null)}
        onConfirm={archiveCollection}
        open={Boolean(archiving)}
        title="Archive this collection?"
      />
    </>
  );
}
