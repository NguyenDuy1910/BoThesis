"use client";

import {
  Activity,
  Check,
  CircleAlert,
  Database,
  FileText,
  KeyRound,
  Layers,
  Lock,
  Plus,
  RefreshCw,
  ShieldCheck,
  Users,
  UsersRound,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { LoadingState } from "@/components/ui/LoadingState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { adminRequest, queryString } from "@/modules/admin/api";

type AdminRow = Record<string, any>;

interface PaginatedResult {
  items: AdminRow[];
  total: number;
  page: number;
  page_size: number;
}

interface OverviewResult {
  tenant: { id: string; code: string; name: string; status: string; updated_at: string };
  metrics: Record<string, number>;
  attention: Record<string, number>;
  recent_activity: AdminRow[];
  generated_at: string;
}

interface SectionDefinition {
  endpoint: string;
  title: string;
  description: string;
  emptyTitle: string;
  createLabel?: string;
  statusOptions?: { value: string; label: string }[];
}

const PAGE_SIZE = 20;

const sections: Record<string, SectionDefinition> = {
  connectors: {
    endpoint: "/datasources",
    title: "Data Sources",
    description: "Configure trusted source boundaries, validate connections, and start governed synchronization.",
    emptyTitle: "No data sources configured",
    createLabel: "Add data source",
    statusOptions: statusOptions("draft", "active", "disabled", "error"),
  },
  "ingestion/jobs": {
    endpoint: "/ingestion/jobs",
    title: "Ingestion",
    description: "Track durable source generations from discovery through indexing and activation.",
    emptyTitle: "No ingestion runs recorded",
    statusOptions: statusOptions("pending", "running", "completed", "failed", "cancelled"),
  },
  documents: {
    endpoint: "/documents",
    title: "Documents",
    description: "Inspect tenant document lineage, processing state, source association, and lifecycle.",
    emptyTitle: "No enterprise documents indexed",
    statusOptions: statusOptions("active", "hidden", "retired", "failed", "unsupported"),
  },
  users: {
    endpoint: "/users",
    title: "Users",
    description: "Manage tenant membership, durable roles, group grants, and account state.",
    emptyTitle: "No tenant users found",
    createLabel: "Add user",
    statusOptions: statusOptions("active", "inactive"),
  },
  groups: {
    endpoint: "/groups",
    title: "Groups",
    description: "Combine permission grants with reusable document ACL principal tokens.",
    emptyTitle: "No groups configured",
    createLabel: "Create group",
    statusOptions: statusOptions("active", "inactive"),
  },
  "access-requests": {
    endpoint: "/access-requests",
    title: "Access Requests",
    description: "Review pending grants and apply approved access in the same database transaction.",
    emptyTitle: "No access requests found",
    createLabel: "Create request",
    statusOptions: statusOptions("pending", "approved", "denied", "cancelled"),
  },
  roles: {
    endpoint: "/roles",
    title: "Roles",
    description: "Define the application capabilities attached to each tenant membership.",
    emptyTitle: "No roles configured",
    createLabel: "Create role",
    statusOptions: statusOptions("active", "inactive"),
  },
  acl: {
    endpoint: "/acl-policies",
    title: "ACL Policies",
    description: "Materialize allowed and denied principal tokens onto governed documents.",
    emptyTitle: "No ACL policies configured",
    createLabel: "Create policy",
    statusOptions: statusOptions("active", "inactive"),
  },
  "audit-logs": {
    endpoint: "/audit-logs",
    title: "Audit Logs",
    description: "Review append-only administration events without private content or secret values.",
    emptyTitle: "No administration events recorded",
  },
};

export function AdminPage({ section }: { section: string }) {
  if (section === "overview" || !section) return <OverviewPage />;
  if (section === "spaces") return <SpacesPage />;
  const definition = sections[section];
  if (!definition) {
    return (
      <EmptyState
        icon={<CircleAlert className="h-5 w-5" />}
        title="Admin route not found"
        description="This route is not part of the BoThesis control plane."
      />
    );
  }
  return <ResourcePage definition={definition} section={section} />;
}

function OverviewPage() {
  const query = useAdminQuery<OverviewResult>("/overview");
  if (query.loading) return <LoadingState title="Loading tenant control plane" />;
  if (query.error || !query.data) {
    return <ErrorState description={query.error ?? "The overview response was empty."} actionLabel="Retry" onAction={query.reload} />;
  }
  const { tenant, metrics, attention, recent_activity: recentActivity } = query.data;
  const evidence = [
    { label: "Active users", value: metrics.active_users, icon: Users },
    { label: "Data sources", value: metrics.active_datasources, icon: Database },
    { label: "Documents", value: metrics.documents, icon: FileText },
    { label: "Open attention", value: Object.values(attention).reduce((sum, value) => sum + value, 0), icon: CircleAlert },
  ];
  return (
    <div className="mx-auto min-w-0 w-full max-w-[88rem]">
      <PageHeader
        title={tenant.name}
        description="A tenant-scoped view of identity, source, ingestion, and access state. Every value comes from durable backend records."
        metadata={<><span className="font-mono">{tenant.code}</span><StatusBadge status={tenant.status} /></>}
      />
      <div className="mb-5 grid border-y border-[var(--border)] bg-[var(--surface)] sm:grid-cols-2 xl:grid-cols-4">
        {evidence.map(({ label, value, icon: Icon }, index) => (
          <div className={`flex min-h-24 items-center gap-3 px-4 py-3 ${index ? "border-t border-[var(--border)] sm:border-l sm:border-t-0" : ""}`} key={label}>
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-[var(--primary-soft)] text-[var(--brand-accent)] ring-1 ring-inset ring-[var(--border)]">
              <Icon aria-hidden="true" className="h-4 w-4" />
            </span>
            <div><p className="font-mono text-2xl font-semibold text-[var(--text)]">{value.toLocaleString()}</p><p className="text-xs text-[var(--text-muted)]">{label}</p></div>
          </div>
        ))}
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Recent administration activity</h2></CardHeader>
          {recentActivity.length ? (
            <DataTable columns={columnsFor("audit-logs")} data={recentActivity} density="dense" emptyMessage="No recent activity" />
          ) : (
            <EmptyState size="sm" title="No administration activity yet" description="Mutations will appear here as append-only audit events." />
          )}
        </Card>
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-[var(--text)]">Needs attention</h2></CardHeader>
          <CardBody className="space-y-1 p-0">
            {Object.entries(attention).map(([key, value]) => (
              <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3 last:border-b-0" key={key}>
                <span className="text-sm text-[var(--text-secondary)]">{titleCase(key)}</span>
                <Badge variant={value ? "warning" : "success"}>{value}</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function SpacesPage() {
  const query = useAdminQuery<PaginatedResult>("/spaces");
  const [editing, setEditing] = useState(false);
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  if (query.loading) return <LoadingState title="Loading tenant space" />;
  if (query.error || !query.data) return <ErrorState description={query.error ?? "The space response was empty."} actionLabel="Retry" onAction={query.reload} />;
  const space = query.data.items[0];
  if (!space) return <EmptyState icon={<Layers className="h-5 w-5" />} title="No tenant space found" />;
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    try {
      await adminRequest(`/spaces/${space.id}`, { method: "PATCH", body: JSON.stringify({ name: String(form.get("name") ?? "") }) });
      toast({ title: "Space updated", variant: "success" });
      setEditing(false);
      query.reload();
    } catch (error) {
      toast({ title: "Space update failed", description: message(error), variant: "error" });
    } finally { setSaving(false); }
  }
  return (
    <div className="mx-auto min-w-0 w-full max-w-5xl">
      <PageHeader title="Spaces" description="The current identity model permits one governed tenant membership per user." actions={<Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} variant="secondary" onClick={query.reload}>Refresh</Button>} />
      <Card>
        <CardHeader className="flex items-center justify-between gap-3"><div><h2 className="text-base font-semibold text-[var(--text)]">{space.name}</h2><p className="mt-0.5 font-mono text-xs text-[var(--text-muted)]">{space.code} · {space.id}</p></div><Button variant="secondary" onClick={() => setEditing(true)}>Edit profile</Button></CardHeader>
        <CardBody className="grid gap-4 sm:grid-cols-3">
          <Detail label="Status"><StatusBadge status={space.status} /></Detail>
          <Detail label="Created">{formatDate(space.created_at)}</Detail>
          <Detail label="Updated">{formatDate(space.updated_at)}</Detail>
        </CardBody>
      </Card>
      <Dialog open={editing} onClose={() => setEditing(false)} title="Edit space" footer={<><Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button><Button form="space-edit-form" loading={saving} type="submit">Save changes</Button></>}>
        <form id="space-edit-form" onSubmit={save}><FormField htmlFor="space-name" label="Space name" required><Input id="space-name" name="name" defaultValue={space.name} required /></FormField></form>
      </Dialog>
    </div>
  );
}

function ResourcePage({ definition, section }: { definition: SectionDefinition; section: string }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const path = `${definition.endpoint}${queryString({ page, page_size: PAGE_SIZE, search, status: statusFilter })}`;
  const query = useAdminQuery<PaginatedResult>(path);
  const onSearch = useCallback((value: string) => { setSearch(value); setPage(1); }, []);
  const metadata = query.data ? <span>{query.data.total.toLocaleString()} {query.data.total === 1 ? "record" : "records"}</span> : undefined;
  return (
    <div className="mx-auto min-w-0 w-full max-w-[92rem]">
      <PageHeader
        title={definition.title}
        description={definition.description}
        metadata={metadata}
        actions={<><Button icon={<RefreshCw aria-hidden="true" className="h-4 w-4" />} variant="secondary" onClick={query.reload}>Refresh</Button>{definition.createLabel && <Button icon={<Plus aria-hidden="true" className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>{definition.createLabel}</Button>}</>}
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <SearchInput ariaLabel={`Search ${definition.title}`} className="w-full sm:max-w-sm" onChange={onSearch} placeholder={`Search ${definition.title.toLowerCase()}…`} value={search} />
        {definition.statusOptions && <Select aria-label="Filter by status" className="w-full sm:w-44" options={[{ value: "", label: "All statuses" }, ...definition.statusOptions]} value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} />}
      </div>
      {query.loading && <LoadingState title={`Loading ${definition.title.toLowerCase()}`} />}
      {query.error && <ErrorState description={query.error} actionLabel="Retry" onAction={query.reload} />}
      {query.data && !query.loading && !query.error && (
        <Card className="min-w-0 overflow-hidden">
          <DataTable
            columns={columnsFor(section)}
            data={query.data.items}
            density="dense"
            emptyMessage={definition.emptyTitle}
            rowActions={(row) => <ResourceActions reload={query.reload} row={row} section={section} />}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={query.data.total} onPageChange={setPage} />
        </Card>
      )}
      {definition.createLabel && <CreateResourceDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={query.reload} section={section} title={definition.createLabel} />}
    </div>
  );
}

function ResourceActions({ reload, row, section }: { reload: () => void; row: AdminRow; section: string }) {
  const { toast } = useToast();
  const [pending, setPending] = useState<string | null>(null);
  const mutate = useCallback(async (label: string, path: string, method = "POST", body?: unknown) => {
    setPending(label);
    try {
      await adminRequest(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      toast({ title: label, variant: "success" });
      reload();
    } catch (error) {
      toast({ title: `${label} failed`, description: message(error), variant: "error" });
    } finally { setPending(null); }
  }, [reload, toast]);
  const action = (label: string, path: string, method = "POST", body?: unknown, variant: "primary" | "secondary" | "danger" = "secondary") => (
    <Button key={label} loading={pending === label} onClick={() => mutate(label, path, method, body)} size="sm" variant={variant}>{label}</Button>
  );
  if (section === "connectors") {
    return <div className="flex justify-end gap-1">{["draft", "error"].includes(row.status) && action("Validate", `/datasources/${row.id}/validate`)}{row.status === "active" && action("Sync", `/datasources/${row.id}/sync`, "POST", {})}{row.status === "active" && action("Disable", `/datasources/${row.id}`, "PATCH", { status: "disabled" })}{row.status === "disabled" && action("Enable", `/datasources/${row.id}`, "PATCH", { status: "active" })}</div>;
  }
  if (section === "ingestion/jobs") {
    return <div className="flex justify-end gap-1">{["pending", "running"].includes(row.status) && action("Cancel", `/ingestion/jobs/${row.id}/cancel`, "POST", undefined, "danger")}{["failed", "cancelled"].includes(row.status) && action("Retry", `/ingestion/jobs/${row.id}/retry`)}</div>;
  }
  if (section === "documents") {
    return <div className="flex justify-end gap-1">{(row.indexing_status === "failed" || row.lifecycle_status === "failed") && action("Retry", `/documents/${row.id}/retry`)}{row.lifecycle_status === "active" && action("Hide", `/documents/${row.id}`, "PATCH", { lifecycle_status: "hidden" })}{row.lifecycle_status === "hidden" && action("Restore", `/documents/${row.id}`, "PATCH", { lifecycle_status: "active" })}</div>;
  }
  if (["users", "groups", "roles"].includes(section)) {
    const next = row.status === "active" ? "inactive" : "active";
    return action(next === "active" ? "Enable" : "Disable", `/${section}/${row.id}`, "PATCH", { status: next }, next === "inactive" ? "danger" : "secondary");
  }
  if (section === "access-requests" && row.status === "pending") {
    return <div className="flex justify-end gap-1">{action("Approve", `/access-requests/${row.id}/decision`, "POST", { decision: "approved" }, "primary")}{action("Deny", `/access-requests/${row.id}/decision`, "POST", { decision: "denied" }, "danger")}</div>;
  }
  if (section === "acl") {
    const next = row.status === "active" ? "inactive" : "active";
    return action(next === "active" ? "Enable" : "Disable", `/acl-policies/${row.id}`, "PATCH", { status: next }, next === "inactive" ? "danger" : "secondary");
  }
  return <span className="text-xs text-[var(--text-muted)]">Read only</span>;
}

function CreateResourceDialog({ onClose, onCreated, open, section, title }: { onClose: () => void; onCreated: () => void; open: boolean; section: string; title: string }) {
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dependencies = useCreateDependencies(open, section);
  const formId = `create-${section.replaceAll("/", "-")}`;
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const form = new FormData(event.currentTarget);
      const { endpoint, payload } = createPayload(section, form);
      await adminRequest(endpoint, { method: "POST", body: JSON.stringify(payload) });
      toast({ title: `${title} completed`, variant: "success" });
      onClose();
      onCreated();
    } catch (caught) {
      const detail = message(caught);
      setError(detail);
      toast({ title: `${title} failed`, description: detail, variant: "error" });
    } finally { setSaving(false); }
  }
  return (
    <Dialog open={open} onClose={onClose} title={title} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button form={formId} loading={saving} type="submit">{title}</Button></>}>
      <form className="space-y-4" id={formId} onSubmit={submit}>
        {error && <ErrorState description={error} />}
        <CreateFields dependencies={dependencies} section={section} />
      </form>
    </Dialog>
  );
}

function CreateFields({ dependencies, section }: { dependencies: Record<string, AdminRow[]>; section: string }) {
  if (section === "users") return <><Field name="email" label="Email" type="email" /><Field name="display_name" label="Display name" /><FormField label="Role" htmlFor="new-user-role" required><Select id="new-user-role" name="role_id" required placeholder="Select a role" options={(dependencies.roles ?? []).map((role) => ({ value: role.id, label: `${role.display_name} (${role.code})` }))} /></FormField><Field name="group_ids" label="Group IDs" helper="Optional comma-separated group UUIDs." /></>;
  if (section === "roles") return <><Field name="code" label="Role code" /><Field name="display_name" label="Display name" /><Field name="permission_codes" label="Permission codes" helper="Comma-separated application capabilities, for example knowledge.read, source.manage." /></>;
  if (section === "groups") return <><Field name="code" label="Group code" /><Field name="display_name" label="Display name" /><Field name="description" label="Description" required={false} /><Field name="permission_codes" label="Permission codes" helper="Optional comma-separated capabilities contributed by this group." required={false} /></>;
  if (section === "connectors") return <><FormField label="Provider" htmlFor="new-source-provider" required><Select id="new-source-provider" name="provider" options={[{ value: "file", label: "Managed files" }, { value: "confluence", label: "Confluence" }]} /></FormField><Field name="display_name" label="Display name" /><Field name="base_dir" label="Managed file directory" helper="Used only for the managed-file provider." required={false} /><Field name="wiki_base" label="Confluence URL" helper="Used only for Confluence, for example https://company.atlassian.net/wiki." required={false} /><Field name="space" label="Confluence space key" required={false} /><Field name="credential_secret_ref" label="Credential reference" helper="Use an env:// reference. Never paste secret values here." required={false} /></>;
  if (section === "access-requests") return <><FormField label="Requester" htmlFor="new-request-user" required><Select id="new-request-user" name="requester_user_id" required placeholder="Select a user" options={(dependencies.users ?? []).map((user) => ({ value: user.id, label: user.display_name ? `${user.display_name} · ${user.email}` : user.email }))} /></FormField><FormField label="Resource type" htmlFor="new-request-type" required><Select id="new-request-type" name="resource_type" options={[{ value: "document", label: "Document" }, { value: "group", label: "Group" }, { value: "role", label: "Role" }]} /></FormField><Field name="resource_id" label="Resource UUID" /><Field name="access_type" label="Access type" defaultValue="read" /><Field name="reason" label="Reason" required={false} /></>;
  if (section === "acl") return <><Field name="name" label="Policy name" /><FormField label="Document" htmlFor="new-policy-document" required><Select id="new-policy-document" name="resource_id" required placeholder="Select a document" options={(dependencies.documents ?? []).map((document) => ({ value: document.id, label: document.title ?? document.id }))} /></FormField><Field name="allowed_principal_tokens" label="Allowed principals" helper="Comma-separated tokens such as group:finance or email:user@example.com." /><Field name="denied_principal_tokens" label="Denied principals" helper="Optional comma-separated deny tokens." required={false} /></>;
  return null;
}

function Field({ defaultValue, helper, label, name, required = true, type = "text" }: { defaultValue?: string; helper?: string; label: string; name: string; required?: boolean; type?: string }) {
  return <FormField helperText={helper} htmlFor={`field-${name}`} label={label} required={required}><Input autoComplete="off" defaultValue={defaultValue} id={`field-${name}`} name={name} required={required} type={type} /></FormField>;
}

function useCreateDependencies(open: boolean, section: string) {
  const [dependencies, setDependencies] = useState<Record<string, AdminRow[]>>({});
  useEffect(() => {
    if (!open) return;
    const requests: [string, string][] = [];
    if (section === "users") requests.push(["roles", "/roles?page_size=100&status=active"]);
    if (section === "access-requests") requests.push(["users", "/users?page_size=100&status=active"]);
    if (section === "acl") requests.push(["documents", "/documents?page_size=100&lifecycle_status=active"]);
    let active = true;
    Promise.all(requests.map(async ([key, path]) => [key, (await adminRequest<PaginatedResult>(path)).items] as const)).then((entries) => { if (active) setDependencies(Object.fromEntries(entries)); }).catch(() => { if (active) setDependencies({}); });
    return () => { active = false; };
  }, [open, section]);
  return dependencies;
}

function createPayload(section: string, form: FormData): { endpoint: string; payload: AdminRow } {
  const value = (name: string) => String(form.get(name) ?? "").trim();
  const list = (name: string) => value(name).split(",").map((item) => item.trim()).filter(Boolean);
  if (section === "users") return { endpoint: "/users", payload: { email: value("email"), display_name: value("display_name"), role_id: value("role_id"), group_ids: list("group_ids") } };
  if (section === "roles") return { endpoint: "/roles", payload: { code: value("code"), display_name: value("display_name"), permission_codes: list("permission_codes") } };
  if (section === "groups") return { endpoint: "/groups", payload: { code: value("code"), display_name: value("display_name"), description: value("description") || undefined, permission_codes: list("permission_codes") } };
  if (section === "connectors") {
    const provider = value("provider");
    const settings = provider === "confluence" ? { wiki_base: value("wiki_base"), is_cloud: true, space: value("space") } : { base_dir: value("base_dir") || "/tmp/bothesis-manual-uploads" };
    return { endpoint: "/datasources", payload: { provider, display_name: value("display_name"), settings, credential_secret_ref: value("credential_secret_ref") || undefined } };
  }
  if (section === "access-requests") return { endpoint: "/access-requests", payload: { requester_user_id: value("requester_user_id"), resource_type: value("resource_type"), resource_id: value("resource_id"), access_type: value("access_type"), reason: value("reason") || undefined } };
  if (section === "acl") return { endpoint: "/acl-policies", payload: { name: value("name"), resource_type: "document", resource_id: value("resource_id"), allowed_principal_tokens: list("allowed_principal_tokens"), denied_principal_tokens: list("denied_principal_tokens") } };
  throw new Error("This resource cannot be created from the current Admin screen.");
}

function useAdminQuery<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    adminRequest<T>(path, { signal: controller.signal })
      .then(setData)
      .catch((caught) => { if (!controller.signal.aborted) setError(message(caught)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, revision]);
  return { data, error, loading, reload };
}

function columnsFor(section: string): Column<AdminRow>[] {
  const id = { key: "id", label: "ID", width: 112, render: (row: AdminRow) => <code className="font-mono text-[0.6875rem] text-[var(--text-muted)]" title={row.id}>{shortId(row.id)}</code> };
  if (section === "connectors") return [{ key: "display_name", label: "Data source", sortable: true, render: (row) => <Identity primary={row.display_name} secondary={titleCase(row.provider)} /> }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "scope_count", label: "Scopes", align: "right" }, { key: "document_count", label: "Documents", align: "right" }, { key: "last_synced_at", label: "Last synced", render: (row) => formatDate(row.last_synced_at) }, id];
  if (section === "ingestion/jobs") return [{ key: "datasource", label: "Data source", render: (row) => <Identity primary={row.datasource?.display_name ?? "Unknown source"} secondary={row.scope?.display_name ?? "Unknown scope"} /> }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "progress", label: "Indexed", render: (row) => `${row.indexed_document_count}/${row.discovered_document_count}` }, { key: "generation", label: "Generation", align: "right" }, { key: "created_at", label: "Created", render: (row) => formatDate(row.created_at) }, id];
  if (section === "documents") return [{ key: "title", label: "Document", sortable: true, render: (row) => <Identity primary={row.title ?? "Untitled document"} secondary={`${titleCase(row.origin)} · ${formatBytes(row.size_bytes)}`} /> }, { key: "datasource", label: "Source", render: (row) => row.datasource?.display_name ?? "Tenant created" }, { key: "indexing_status", label: "Indexing", render: (row) => <StatusBadge status={row.indexing_status} /> }, { key: "lifecycle_status", label: "Lifecycle", render: (row) => <StatusBadge status={row.lifecycle_status} /> }, { key: "updated_at", label: "Updated", render: (row) => formatDate(row.updated_at) }, id];
  if (section === "users") return [{ key: "display_name", label: "User", sortable: true, render: (row) => <Identity primary={row.display_name ?? row.email} secondary={row.display_name ? row.email : "No display name"} /> }, { key: "role", label: "Role", render: (row) => row.membership?.role?.display_name ?? "No role" }, { key: "groups", label: "Groups", render: (row) => row.groups?.length ? row.groups.map((group: AdminRow) => group.display_name).join(", ") : "None" }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "last_login_at", label: "Last login", render: (row) => formatDate(row.last_login_at) }, id];
  if (section === "groups") return [{ key: "display_name", label: "Group", sortable: true, render: (row) => <Identity primary={row.display_name} secondary={row.principal_token} /> }, { key: "member_count", label: "Members", align: "right" }, { key: "permission_codes", label: "Permissions", render: (row) => row.permission_codes?.length ?? 0 }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "updated_at", label: "Updated", render: (row) => formatDate(row.updated_at) }, id];
  if (section === "access-requests") return [{ key: "requester", label: "Requester", render: (row) => <Identity primary={row.requester?.display_name ?? row.requester?.email} secondary={row.requester?.email} /> }, { key: "resource_type", label: "Resource", render: (row) => <Identity primary={titleCase(row.resource_type)} secondary={shortId(row.resource_id)} /> }, { key: "access_type", label: "Access" }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "created_at", label: "Requested", render: (row) => formatDate(row.created_at) }, id];
  if (section === "roles") return [{ key: "display_name", label: "Role", sortable: true, render: (row) => <Identity primary={row.display_name} secondary={row.code} /> }, { key: "member_count", label: "Members", align: "right" }, { key: "permission_codes", label: "Permissions", render: (row) => row.permission_codes?.length ? row.permission_codes.join(", ") : "None" }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "updated_at", label: "Updated", render: (row) => formatDate(row.updated_at) }, id];
  if (section === "acl") return [{ key: "name", label: "Policy", sortable: true, render: (row) => <Identity primary={row.name} secondary={row.resource_title ?? shortId(row.resource_id)} /> }, { key: "allowed", label: "Allow", align: "right", render: (row) => row.allowed_principal_tokens?.length ?? 0 }, { key: "denied", label: "Deny", align: "right", render: (row) => row.denied_principal_tokens?.length ?? 0 }, { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} /> }, { key: "updated_at", label: "Updated", render: (row) => formatDate(row.updated_at) }, id];
  return [{ key: "created_at", label: "Time", render: (row) => formatDate(row.created_at) }, { key: "actor", label: "Actor", render: (row) => row.actor?.display_name ?? row.actor?.email ?? "System" }, { key: "action", label: "Action", render: (row) => titleCase(row.action) }, { key: "resource_type", label: "Resource", render: (row) => <Identity primary={titleCase(row.resource_type)} secondary={shortId(row.resource_id)} /> }, { key: "outcome", label: "Outcome", render: (row) => <StatusBadge status={row.outcome} /> }];
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status?.toLowerCase() ?? "unknown";
  const variant = ["active", "approved", "completed", "indexed", "success", "available"].includes(normalized) ? "success" : ["failed", "error", "denied", "unsupported"].includes(normalized) ? "danger" : ["pending", "running", "draft"].includes(normalized) ? "warning" : ["disabled", "inactive", "cancelled", "hidden", "retired", "none"].includes(normalized) ? "default" : "info";
  return <Badge dot variant={variant}>{titleCase(normalized)}</Badge>;
}

function Identity({ primary, secondary }: { primary: string; secondary?: string }) {
  return <div className="min-w-0"><p className="truncate font-medium text-[var(--text)]">{primary}</p>{secondary && <p className="truncate text-xs text-[var(--text-muted)]">{secondary}</p>}</div>;
}

function Detail({ children, label }: { children: React.ReactNode; label: string }) {
  return <div><p className="mb-1 font-mono text-[0.6875rem] uppercase tracking-[0.05em] text-[var(--text-muted)]">{label}</p><div className="text-sm text-[var(--text)]">{children}</div></div>;
}

function formatDate(value?: string | null) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatBytes(value?: number | null) {
  if (!value) return "Size unknown";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** exponent).toFixed(exponent ? 1 : 0)} ${units[exponent]}`;
}

function shortId(value?: string | null) {
  if (!value) return "—";
  return value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function titleCase(value: string) {
  return String(value ?? "").replaceAll(/[._-]/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function statusOptions(...values: string[]) {
  return values.map((value) => ({ value, label: titleCase(value) }));
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "The Admin request could not be completed.";
}
