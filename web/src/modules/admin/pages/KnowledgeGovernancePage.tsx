"use client";

import { BookOpenCheck, ShieldCheck, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { type CollectionGrant, type DirectoryGroup, type DirectoryUser, type KnowledgeItem, type Paginated } from "@/modules/admin/collections";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import { errorMessage } from "@/modules/admin/format";

type PrincipalType = "user" | "group";

interface Grant extends CollectionGrant {
  created_by_user_id?: string | null;
}

/** Collection access is the durable knowledge-governance boundary. */
export function KnowledgeGovernancePage() {
  const { toast } = useToast();
  const collections = useAdminQuery<Paginated<KnowledgeItem>>("/items?item_type=collection&page_size=100");
  const users = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100");
  const groups = useAdminQuery<Paginated<DirectoryGroup>>("/groups?page_size=100");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [principalType, setPrincipalType] = useState<PrincipalType>("user");
  const [principalId, setPrincipalId] = useState("");
  const [role, setRole] = useState<"viewer" | "editor" | "owner">("viewer");
  const [saving, setSaving] = useState(false);

  const selected = (collections.data?.items ?? []).find((collection) => collection.id === selectedId) ?? null;
  const grants = useAdminQuery<Paginated<Grant>>(selected ? `/collections/${selected.id}/access` : null);
  const people = users.data?.items ?? [];
  const groupRows = groups.data?.items ?? [];
  const names = useMemo(() => new Map<string, string>([
    ...people.map((user): [string, string] => [`user:${user.id}`, user.display_name || user.email]),
    ...groupRows.map((group): [string, string] => [`group:${group.id}`, group.display_name]),
  ]), [groupRows, people]);
  const principalOptions = principalType === "user"
    ? people.filter((user) => user.status === "active").map((user) => ({ value: user.id, label: user.display_name || user.email }))
    : groupRows.filter((group) => group.status === "active").map((group) => ({ value: group.id, label: group.display_name }));

  const columns = useMemo<Column<KnowledgeItem>[]>(() => [
    {
      key: "title",
      label: "Collection",
      sortable: true,
      render: (collection) => <CellTitle subtitle={typeof collection.metadata?.description === "string" ? collection.metadata.description : "No description"} title={collection.title} />,
    },
    {
      key: "inherit_access",
      label: "Access model",
      width: 150,
      render: (collection) => <Badge tone={collection.inherit_access ? "neutral" : "brand"}>{collection.inherit_access ? "Inherited" : "Explicit grants"}</Badge>,
    },
    {
      key: "item_count",
      label: "Documents",
      align: "right",
      width: 110,
      render: (collection) => (collection.item_count ?? 0).toLocaleString(),
    },
    {
      key: "source_count",
      label: "Sources",
      align: "right",
      priority: "medium",
      width: 100,
      render: (collection) => (collection.source_count ?? 0).toLocaleString(),
    },
  ], []);

  async function grantAccess() {
    if (!selected || !principalId) return;
    setSaving(true);
    try {
      await adminRequest(`/collections/${selected.id}/access`, {
        method: "PUT",
        body: JSON.stringify({ principal_type: principalType, principal_id: principalId, role }),
      });
      toast({ title: "Collection access saved", variant: "success" });
      setPrincipalId("");
      grants.reload();
    } catch (cause) {
      toast({ title: "Collection access could not be saved", description: errorMessage(cause), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function revokeAccess(grant: Grant) {
    if (!selected) return;
    setSaving(true);
    try {
      await adminRequest(`/collections/${selected.id}/access/${grant.principal_type}/${grant.principal_id}`, { method: "DELETE" });
      toast({ title: "Collection access removed", variant: "success" });
      grants.reload();
    } catch (cause) {
      toast({ title: "Collection access could not be removed", description: errorMessage(cause), variant: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader description="Review collection scope, inherited access, and the people or groups with explicit knowledge grants." title="Knowledge governance" />
      <p className="mb-4 rounded-[var(--radius-md)] bg-[var(--status-info-bg)] px-3.5 py-3 text-[0.8125rem] text-[var(--status-info-text)]">Source permissions and collection access are evaluated when knowledge is retrieved. An explicit collection grant never gives someone platform access.</p>
      <ResourceList
        ariaLabel="Governed collections"
        columns={columns}
        empty={<EmptyState description="Create a collection before defining its knowledge access." icon={<BookOpenCheck className="h-5 w-5" />} title="No collections yet" />}
        error={collections.error}
        loading={collections.loading}
        onRetry={collections.reload}
        onRowClick={(collection) => setSelectedId(collection.id)}
        rows={collections.data?.items ?? []}
        rowActions={() => <Button size="sm" variant="secondary">Manage access</Button>}
      />

      <Sheet onClose={() => setSelectedId(null)} open={Boolean(selected)} title={selected ? `${selected.title} access` : "Collection access"}>
        <div className="space-y-5 p-5 sm:p-6">
          <div className="rounded-[var(--radius-md)] bg-[var(--surface-inset)] p-3.5">
            <div className="flex items-start gap-2"><ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-accent)]" /><p className="text-[0.8125rem] leading-5 text-[var(--text-secondary)]">{selected?.inherit_access ? "This collection inherits its baseline. Add an explicit grant only for a documented exception." : "This collection uses explicit grants. Only listed people and groups receive the assigned collection role."}</p></div>
          </div>

          <Card>
            <CardHeader description="Choose an active workspace person or group and the role they need in this collection." title="Add or update access" />
            <CardBody>
              <div className="grid gap-3">
                <FormField htmlFor="governance-principal-type" label="Principal type"><Select id="governance-principal-type" onChange={(event) => { setPrincipalType(event.target.value as PrincipalType); setPrincipalId(""); }} options={[{ value: "user", label: "Person" }, { value: "group", label: "Group" }]} value={principalType} /></FormField>
                <FormField htmlFor="governance-principal" label={principalType === "user" ? "Person" : "Group"}><Select id="governance-principal" onChange={(event) => setPrincipalId(event.target.value)} options={principalOptions} placeholder={principalOptions.length ? `Choose a ${principalType}` : `No active ${principalType}s`} value={principalId} /></FormField>
                <FormField htmlFor="governance-role" label="Collection role"><Select id="governance-role" onChange={(event) => setRole(event.target.value as typeof role)} options={[{ value: "viewer", label: "Viewer — retrieve and read" }, { value: "editor", label: "Editor — manage collection content" }, { value: "owner", label: "Owner — manage collection access" }]} value={role} /></FormField>
                <Button disabled={!principalId} loading={saving} onClick={grantAccess}>Save collection access</Button>
              </div>
            </CardBody>
          </Card>

          <section aria-labelledby="collection-grants-title">
            <div className="mb-2 flex items-center justify-between"><h3 className="text-[0.8125rem] font-semibold text-[var(--text-primary)]" id="collection-grants-title">Explicit grants</h3><span className="text-[0.75rem] text-[var(--text-tertiary)]">{grants.data?.total ?? 0}</span></div>
            {grants.error ? <ErrorState actionLabel="Try again" description={grants.error} layout="inline" onAction={grants.reload} title="Access grants could not be loaded" /> : grants.loading ? <p className="text-[0.8125rem] text-[var(--text-tertiary)]">Loading grants…</p> : (grants.data?.items.length ?? 0) === 0 ? <EmptyState description="No explicit people or group grants are stored for this collection." icon={<Users className="h-5 w-5" />} title="No explicit grants" /> : <ul className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-md)] border border-[var(--border-subtle)]">{grants.data?.items.map((grant) => <li className="flex items-center gap-3 px-3 py-3" key={`${grant.principal_type}:${grant.principal_id}`}><Users aria-hidden="true" className="h-4 w-4 shrink-0 text-[var(--text-tertiary)]" /><span className="min-w-0 flex-1"><span className="block truncate text-[0.8125rem] font-medium text-[var(--text-primary)]">{names.get(`${grant.principal_type}:${grant.principal_id}`) ?? String(grant.principal_id)}</span><span className="text-[0.75rem] text-[var(--text-tertiary)]">{String(grant.principal_type)}</span></span><Badge tone="neutral">{String(grant.role)}</Badge><Button aria-label="Remove collection access" icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />} iconOnly loading={saving} onClick={() => revokeAccess(grant)} size="sm" variant="ghost" /></li>)}</ul>}
          </section>
        </div>
      </Sheet>
    </>
  );
}
