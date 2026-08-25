"use client";

import {
  ArrowRight,
  ChevronRight,
  CircleAlert,
  FolderTree,
  Power,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import {
  adminRequest,
  useAdminQuery,
} from "@/modules/admin/api";
import {
  connectorCategories,
  connectorDefinition,
  connectorDefinitions,
  type ConnectorCategory,
  type ConnectorDefinition,
} from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import {
  ConnectorSection,
  type ConnectorSectionItem,
} from "@/modules/connectors/components/ConnectorSection";
import type { ConnectorRegistryStatus } from "@/modules/connectors/types";

type AdminRow = Record<string, any>;
type RegistryFilter = "all" | "installed" | "available" | "disabled" | ConnectorCategory;

interface PluginCapability {
  plugin_key: string;
  display_name: string;
  authentication_type: string;
  capabilities: string[];
}

interface ConnectorCapabilities {
  plugins: PluginCapability[];
}

interface PaginatedResult {
  items: AdminRow[];
  total: number;
}

const registryFilters: ReadonlyArray<{ id: RegistryFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "installed", label: "Installed" },
  { id: "available", label: "Available" },
  { id: "disabled", label: "Disabled" },
  ...connectorCategories,
];

/** Tenant connector registry, separate from configured connection instances. */
export function ConnectorRegistryPage() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<RegistryFilter>("all");
  const [selected, setSelected] = useState<ConnectorDefinition | null>(null);
  const [setupKey, setSetupKey] = useState(0);
  const connections = useAdminQuery<PaginatedResult>("/plugin-connections?page_size=100");
  const capabilities = useAdminQuery<ConnectorCapabilities>("/plugins/capabilities");

  const availableProviders = useMemo(
    () => new Set(capabilities.data?.plugins.map((item) => item.plugin_key) ?? []),
    [capabilities.data],
  );
  const instancesByProvider = useMemo(() => {
    const result = new Map<string, AdminRow[]>();
    for (const connection of connections.data?.items ?? []) {
      result.set(connection.plugin_key, [...(result.get(connection.plugin_key) ?? []), connection]);
    }
    return result;
  }, [connections.data?.items]);
  const registryItems = useMemo<ConnectorSectionItem[]>(() => {
    const term = search.trim().toLocaleLowerCase();
    return connectorDefinitions.flatMap((connector) => {
      const instances = instancesByProvider.get(connector.provider) ?? [];
      const status = connectorRegistryStatus(
        instances,
        availableProviders.has(connector.provider),
      );
      const matchesSearch = !term || `${connector.name} ${connector.description} ${connector.category}`.toLocaleLowerCase().includes(term);
      const matchesFilter = filter === "all"
        || filter === "installed" && instances.length > 0
        || filter === "available" && status === "available"
        || filter === "disabled" && status === "disabled"
        || connector.category === filter;
      return matchesSearch && matchesFilter
        ? [{ connector, connectionCount: instances.length, status }]
        : [];
    });
  }, [availableProviders, filter, instancesByProvider, search]);
  const sections = registrySections(registryItems, filter, Boolean(search.trim()));

  function openDetails(connector: ConnectorDefinition) {
    setSetupKey((value) => value + 1);
    setSelected(connector);
  }

  return (
    <div className="mx-auto min-w-0 w-full max-w-[88rem]">
      <PageHeader
        title="Connector Registry"
        description="Enable trusted integrations, manage connection instances, and control what BoThesis can search."
        metadata={<span>{connectorDefinitions.length} connector types{connections.data?.total ? ` · ${connections.data.total} configured` : ""}</span>}
      />

      <section aria-labelledby="connector-search-heading" className="mb-8">
        <h2 className="sr-only" id="connector-search-heading">Find a connector</h2>
        <SearchInput
          ariaLabel="Search connectors"
          className="w-full max-w-xl"
          debounceMs={0}
          onChange={setSearch}
          placeholder="Search connectors…"
          value={search}
        />
        <div aria-label="Filter connectors" className="connector-filterbar" role="group">
          {registryFilters.map((item) => (
            <button
              aria-pressed={filter === item.id}
              className={cn("connector-filter", filter === item.id && "connector-filter--active")}
              key={item.id}
              onClick={() => setFilter(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      {capabilities.loading && connections.loading ? <ConnectorRegistrySkeleton /> : registryItems.length ? (
        <div className="space-y-10">
          {sections.map((section) => (
            <ConnectorSection
              description={section.description}
              items={section.items}
              key={section.title}
              onSelect={openDetails}
              title={section.title}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<CircleAlert aria-hidden="true" className="h-5 w-5" />}
          size="sm"
          title="No connectors match that search"
          description="Try another name or clear the current registry filter."
        />
      )}

      <ConnectionsSection
        error={connections.error}
        items={connections.data?.items ?? []}
        loading={connections.loading}
        onReload={connections.reload}
      />

      {selected && (
        <ConnectorDetailsDrawer
          available={availableProviders.has(selected.provider)}
          capabilityError={capabilities.error}
          capabilityLoading={capabilities.loading}
          connector={selected}
          connections={instancesByProvider.get(selected.provider) ?? []}
          key={setupKey}
          onClose={() => setSelected(null)}
          onCreated={() => {
            connections.reload();
            setSelected(null);
          }}
        />
      )}
    </div>
  );
}

function connectorRegistryStatus(
  connections: AdminRow[],
  providerAvailable: boolean,
): ConnectorRegistryStatus {
  if (connections.some((connection) => ["running", "syncing"].includes(connection.latest_run?.status))) return "syncing";
  if (connections.some((connection) => connection.status === "active")) return "connected";
  if (connections.some((connection) => connection.status === "error")) return "failed";
  if (connections.some((connection) => connection.status === "draft")) return "needs_setup";
  if (connections.length && connections.every((connection) => connection.status === "disabled")) return "disabled";
  return providerAvailable ? "available" : "unavailable";
}

function registrySections(
  items: ConnectorSectionItem[],
  filter: RegistryFilter,
  searching: boolean,
): Array<{ title: string; description?: string; items: ConnectorSectionItem[] }> {
  if (filter !== "all" || searching) {
    return [{
      title: searching ? "Search results" : registryFilters.find((item) => item.id === filter)?.label ?? "Connectors",
      description: "Connector definitions stay separate from the connection instances configured below.",
      items,
    }];
  }
  const installed = items.filter((item) => item.connectionCount > 0);
  const installedProviders = new Set(installed.map((item) => item.connector.provider));
  const featured = items.filter((item) => item.connector.featured && !installedProviders.has(item.connector.provider));
  const claimed = new Set([...installed, ...featured].map((item) => item.connector.provider));
  return [
    ...(installed.length ? [{ title: "Installed", description: "Tenant connections currently configured in BoThesis.", items: installed }] : []),
    ...(featured.length ? [{ title: "Featured", description: "Common enterprise sources selected for fast discovery.", items: featured }] : []),
    ...connectorCategories.flatMap((category) => {
      const categoryItems = items.filter((item) => item.connector.category === category.id && !claimed.has(item.connector.provider));
      return categoryItems.length ? [{ title: category.label, items: categoryItems }] : [];
    }),
  ];
}

function ConnectorRegistrySkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading connector registry" className="space-y-4">
      <Skeleton className="h-4 w-28" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <div className="min-h-40 rounded-lg bg-[var(--surface)] p-4 ring-1 ring-inset ring-[var(--border)]" key={index}>
            <div className="flex justify-between"><Skeleton className="h-13 w-13 rounded-xl" /><Skeleton className="h-5 w-20 rounded-full" /></div>
            <Skeleton className="mt-4 h-4 w-28" />
            <Skeleton className="mt-2 h-3 w-4/5" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ConnectionsSection({
  error,
  items,
  loading,
  onReload,
}: {
  error: string | null;
  items: AdminRow[];
  loading: boolean;
  onReload: () => void;
}) {
  return (
    <section aria-labelledby="your-connections-heading" className="mt-12 border-t border-[var(--border)] pt-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]" id="your-connections-heading">Your connections</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Configured instances stay separate from the connectors you can add.</p>
        </div>
        {items.length > 0 && <span className="font-mono text-xs text-[var(--text-muted)]">{items.length} configured</span>}
      </div>

      {loading && <ConnectionsSkeleton />}
      {!loading && error && <ErrorState actionLabel="Retry" description={error} onAction={onReload} />}
      {!loading && !error && !items.length && (
        <div className="border-y border-[var(--border)] py-8">
          <EmptyState
            icon={<FolderTree aria-hidden="true" className="h-5 w-5" />}
            size="sm"
            title="No connections yet"
            description="Choose a connector above to configure its first connection."
          />
        </div>
      )}
      {!loading && !error && items.length > 0 && (
        <div className="border-y border-[var(--border)] bg-[var(--surface)]">
          {items.map((connection) => <ConnectionRow connection={connection} key={connection.id} onChanged={onReload} />)}
        </div>
      )}
    </section>
  );
}

function ConnectionsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading connections" className="border-y border-[var(--border)]">
      {Array.from({ length: 2 }).map((_, index) => (
        <div className="flex items-center gap-3 px-4 py-4" key={index}>
          <Skeleton className="h-9 w-9 rounded-lg" />
          <div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-3.5 w-40" /><Skeleton className="h-3 w-28" /></div>
          <Skeleton className="h-6 w-20" />
        </div>
      ))}
    </div>
  );
}

function ConnectionRow({ connection, onChanged }: { connection: AdminRow; onChanged: () => void }) {
  const { toast } = useToast();
  const [action, setAction] = useState<"validate" | "sync" | null>(null);
  const presentation = connectionPresentation(connection);
  const provider = String(connection.plugin_key);

  async function run(actionName: "validate" | "sync") {
    setAction(actionName);
    try {
      const path = `/plugin-connections/${connection.id}/validate`;
      await adminRequest(path, { method: "POST" });
      toast({ title: "Connection verified", description: "Bind it to a knowledge base to start ingestion.", variant: "success" });
      onChanged();
    } catch (cause) {
      toast({ title: actionName === "validate" ? "Connection test failed" : "Could not start ingestion", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4" style={{ contentVisibility: "auto" }}>
      <ConnectorLogo provider={provider} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[var(--text)]" title={connection.display_name}>{connection.display_name}</p>
        <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]" title={connectionScopeSummary(connection)}>{connectionScopeSummary(connection)}</p>
      </div>
      <div className="flex items-center gap-2 sm:justify-end">
        <ConnectionStatus {...presentation} />
        {(connection.status === "draft" || connection.status === "error") && (
          <Button icon={<ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === "validate"} onClick={() => run("validate")} size="sm" variant="secondary">Test</Button>
        )}
        {connection.status === "active" && <Badge variant="primary">Bind in a knowledge base</Badge>}
      </div>
    </div>
  );
}

function ConnectorDetailsDrawer({
  available,
  capabilityError,
  capabilityLoading,
  connector,
  connections,
  onClose,
  onCreated,
}: {
  available: boolean;
  capabilityError: string | null;
  capabilityLoading: boolean;
  connector: ConnectorDefinition;
  connections: AdminRow[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const backendProvider = connector.provider;
  const isFile = backendProvider === "file";
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    if (!hasChanges) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [hasChanges]);

  function requestClose() {
    if (hasChanges && !window.confirm("Discard this connection setup? Your configuration and selected files have not been connected.")) return;
    onClose();
  }

  return (
    <Sheet
      footer={<Button onClick={requestClose} variant="secondary">Close</Button>}
      onClose={requestClose}
      open
      title={connector.name}
    >
      <div className="px-5 py-6 sm:px-6">
        <ConnectorDetailIntro available={available} connector={connector} connectionCount={connections.length} />
        {connections.length > 0 && (
          <ConnectionManagementList connections={connections} onChanged={onCreated} />
        )}
        <div className={cn("mt-7", connections.length > 0 && "border-t border-[var(--border)] pt-7")}>
          <p className="mb-4 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-muted)]">
            {connections.length ? "Add another connection" : "Connection setup"}
          </p>
          {capabilityLoading ? <SetupAvailabilityLoading /> : capabilityError || !available ? (
            <ConnectorNotEnabled error={capabilityError} />
          ) : isFile ? (
            <FileConnectionSetup onCreated={onCreated} onDirtyChange={setHasChanges} />
          ) : (
            <ConfluenceConnectionSetup onCreated={onCreated} onDirtyChange={setHasChanges} />
          )}
        </div>
      </div>
    </Sheet>
  );
}

function ConnectorDetailIntro({
  available,
  connector,
  connectionCount,
}: {
  available: boolean;
  connector: ConnectorDefinition;
  connectionCount: number;
}) {
  return (
    <div className="mb-6">
      <div className="flex items-start gap-4">
        <ConnectorLogo provider={connector.provider} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold tracking-[-0.02em] text-[var(--text)]">{connector.name}</h3>
            <Badge dot variant={connectionCount ? "success" : available ? "default" : "warning"}>
              {connectionCount ? `${connectionCount} configured` : available ? "Available" : "Not enabled"}
            </Badge>
          </div>
          <p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">{connector.description}</p>
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg bg-[var(--bg-panel)] p-4 ring-1 ring-inset ring-[var(--border-muted)]">
        <DetailItem label="Authentication" value={connector.authentication} />
        <DetailItem label="Access boundary" value="Tenant + document ACL" />
        <DetailItem label="Indexing" value={connector.capabilities.includes("Sync") ? "Scoped synchronization" : "Governed ingestion"} />
        <DetailItem label="Tools" value={connector.capabilities.join(" · ")} />
      </dl>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-[0.6875rem] font-medium uppercase tracking-[0.06em] text-[var(--text-muted)]">{label}</dt><dd className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{value}</dd></div>;
}

function ConnectionManagementList({ connections, onChanged }: { connections: AdminRow[]; onChanged: () => void }) {
  return (
    <section aria-labelledby="configured-connector-instances">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-muted)]" id="configured-connector-instances">Connection instances</h4>
      <div className="space-y-2">
        {connections.map((connection) => <ConnectionInstanceCard connection={connection} key={connection.id} onChanged={onChanged} />)}
      </div>
    </section>
  );
}

function ConnectionInstanceCard({ connection, onChanged }: { connection: AdminRow; onChanged: () => void }) {
  const { toast } = useToast();
  const [action, setAction] = useState<"sync" | "test" | "toggle" | "delete" | null>(null);
  const presentation = connectionPresentation(connection);
  const scopes = configuredScopeLabels(connection.config);

  async function run(nextAction: "sync" | "test" | "toggle" | "delete") {
    if (nextAction === "delete" && !window.confirm(`Delete ${connection.display_name}? Indexed records remain governed by their lifecycle policy.`)) return;
    setAction(nextAction);
    try {
      if (nextAction === "sync" || nextAction === "test") await adminRequest(`/plugin-connections/${connection.id}/validate`, { method: "POST" });
      if (nextAction === "toggle") await adminRequest(`/plugin-connections/${connection.id}`, { method: "PATCH", body: JSON.stringify({ status: connection.status === "disabled" ? "active" : "disabled" }) });
      if (nextAction === "delete") await adminRequest(`/plugin-connections/${connection.id}`, { method: "DELETE" });
      toast({ title: nextAction === "sync" || nextAction === "test" ? "Connection verified" : nextAction === "delete" ? "Connection removed" : connection.status === "disabled" ? "Connection enabled" : "Connection disabled", variant: "success" });
      onChanged();
    } catch (cause) {
      toast({ title: "Connection action failed", description: errorMessage(cause), variant: "error" });
    } finally {
      setAction(null);
    }
  }

  return (
    <div className="rounded-lg bg-[var(--surface)] p-3.5 ring-1 ring-inset ring-[var(--border)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--text)]">{connection.display_name}</p>
          <p className="mt-1 truncate text-xs text-[var(--text-muted)]">{scopes.length ? scopes.join(", ") : "Tenant workspace"}</p>
        </div>
        <ConnectionStatus {...presentation} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button icon={<ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === "test" || action === "sync"} onClick={() => run("test")} size="sm" variant="secondary">Test</Button>
        <Button icon={<Power aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === "toggle"} onClick={() => run("toggle")} size="sm" variant="ghost">{connection.status === "disabled" ? "Enable" : "Disable"}</Button>
        <Button icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />} loading={action === "delete"} onClick={() => run("delete")} size="sm" variant="ghost">Delete</Button>
      </div>
    </div>
  );
}

function SetupAvailabilityLoading() {
  return (
    <div aria-busy="true" className="space-y-5">
      <SetupIntro description="Checking whether this connector is enabled for the current deployment." />
      <div className="space-y-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /><Skeleton className="h-10 w-32" /></div>
    </div>
  );
}

function ConnectorNotEnabled({ error }: { error: string | null }) {
  return (
    <div className="space-y-6">
      <SetupIntro description="This connector is discoverable in BoThesis, but it is not enabled in this deployment." />
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)] p-4">
        <p className="text-sm font-medium text-[var(--text)]">A configured connection cannot be created yet.</p>
        <p className="mt-1 text-sm leading-5 text-[var(--text-muted)]">
          Enable the connector service and its authentication boundary before connecting organization content.
        </p>
        {error && <p className="mt-3 text-xs leading-5 text-[var(--danger)]">Availability check failed: {error}</p>}
      </div>
    </div>
  );
}

function ConfluenceConnectionSetup({
  onCreated,
  onDirtyChange,
}: {
  onCreated: () => void;
  onDirtyChange: (hasChanges: boolean) => void;
}) {
  const { toast } = useToast();
  const [connectionName, setConnectionName] = useState("Company Confluence");
  const [siteUrl, setSiteUrl] = useState("");
  const [credentialUsername, setCredentialUsername] = useState("");
  const [credentialToken, setCredentialToken] = useState("");
  const [space, setSpace] = useState("");
  const [includeDescendants, setIncludeDescendants] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const formId = "confluence-connection-setup";

  useEffect(() => {
    onDirtyChange(Boolean(
      createdId
      || siteUrl
      || credentialUsername
      || credentialToken
      || space
      || connectionName !== "Company Confluence"
      || !includeDescendants,
    ));
  }, [connectionName, createdId, credentialToken, credentialUsername, includeDescendants, onDirtyChange, siteUrl, space]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const connectorId = createdId ?? String((await adminRequest<AdminRow>("/plugin-connections", {
        method: "POST",
        body: JSON.stringify({
          plugin_key: "confluence",
          display_name: connectionName.trim(),
          config: {
            wiki_base: siteUrl.trim(),
            is_cloud: true,
            space: space.trim(),
            index_recursively: includeDescendants,
          },
          credentials: {
            confluence_username: credentialUsername.trim(),
            confluence_access_token: credentialToken,
          },
          credential_type: "api_token",
        }),
      })).id);
      setCreatedId(connectorId);
      await adminRequest(`/plugin-connections/${connectorId}/validate`, { method: "POST" });
      toast({ title: "Confluence connected", description: "It is ready to bind to a knowledge base.", variant: "success" });
      onCreated();
    } catch (cause) {
      const detail = errorMessage(cause);
      setError(detail);
      toast({ title: createdId ? "Connection test failed" : "Could not create connection", description: detail, variant: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <SetupIntro description="Add a governed Confluence connection. Credentials are encrypted before they are stored." />
      <SetupSteps labels={["Configure", "Authenticate", "Choose content", "Test connection"]} />
      <form className="mt-6 space-y-5" id={formId} onSubmit={submit}>
        {error && <InlineError description={error} />}
        <FormField htmlFor="confluence-connection-name" label="Connection name" required>
          <Input autoComplete="off" id="confluence-connection-name" maxLength={255} name="display_name" onChange={(event) => setConnectionName(event.target.value)} required value={connectionName} />
        </FormField>
        <FormField helperText="For example, https://company.atlassian.net/wiki." htmlFor="confluence-site-url" label="Confluence site URL" required>
          <Input autoComplete="url" id="confluence-site-url" name="wiki_base" onChange={(event) => setSiteUrl(event.target.value)} placeholder="https://company.atlassian.net/wiki" required type="url" value={siteUrl} />
        </FormField>
        <FormField helperText="The account email used to access this Confluence site." htmlFor="confluence-credential-username" label="Account email" required>
          <Input autoComplete="username" id="confluence-credential-username" name="credential_username" onChange={(event) => setCredentialUsername(event.target.value)} placeholder="person@company.com" required type="email" value={credentialUsername} />
        </FormField>
        <FormField helperText="Stored only as an authenticated-encryption payload." htmlFor="confluence-credential-token" label="API token" required>
          <Input autoComplete="new-password" id="confluence-credential-token" name="credential_token" onChange={(event) => setCredentialToken(event.target.value)} required type="password" value={credentialToken} />
        </FormField>
        <FormField helperText="Leave blank to include all spaces visible to the configured service account." htmlFor="confluence-space" label="Space key">
          <Input autoComplete="off" id="confluence-space" name="space" onChange={(event) => setSpace(event.target.value)} placeholder="ENG" value={space} />
        </FormField>
        <label className="flex min-h-11 items-start gap-3 rounded-md border border-[var(--border)] px-3 py-2.5 text-sm text-[var(--text-secondary)]">
          <input checked={includeDescendants} className="mt-0.5 h-4 w-4 accent-[var(--brand-accent)]" name="index_recursively" onChange={(event) => setIncludeDescendants(event.target.checked)} type="checkbox" />
          <span><span className="font-medium text-[var(--text)]">Include child pages</span><span className="mt-0.5 block text-xs leading-5 text-[var(--text-muted)]">Keep nested space content in scope during each sync.</span></span>
        </label>
      </form>
      <SetupSubmitFooter created={Boolean(createdId)} form={formId} loading={submitting} />
    </>
  );
}

function FileConnectionSetup({
  onCreated,
  onDirtyChange,
}: {
  onCreated: () => void;
  onDirtyChange: (hasChanges: boolean) => void;
}) {
  const { toast } = useToast();
  const [connectionName, setConnectionName] = useState("Uploaded files");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const formId = "file-connection-setup";

  useEffect(() => {
    onDirtyChange(Boolean(createdId || connectionName !== "Uploaded files"));
  }, [connectionName, createdId, onDirtyChange]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const connectorId = createdId ?? String((await adminRequest<AdminRow>("/plugin-connections", {
        method: "POST",
        body: JSON.stringify({ plugin_key: "file", display_name: connectionName.trim(), config: {} }),
      })).id);
      setCreatedId(connectorId);
      await adminRequest(`/plugin-connections/${connectorId}/validate`, { method: "POST" });
      toast({ title: "Managed files connected", description: "It is ready to bind to a knowledge base.", variant: "success" });
      onCreated();
    } catch (cause) {
      const detail = errorMessage(cause);
      setError(detail);
      toast({ title: createdId ? "Connection test failed" : "Could not create connection", description: detail, variant: "error" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <SetupIntro description="Create the governed file source first, then bind it to a knowledge base before adding target-scoped documents." />
      <SetupSteps labels={["Configure", "Test connection", "Bind to knowledge base"]} />
      <form className="mt-6 space-y-5" id={formId} onSubmit={submit}>
        {error && <InlineError description={error} />}
        <FormField htmlFor="file-connection-name" label="Connection name" required>
          <Input autoComplete="off" disabled={Boolean(createdId)} id="file-connection-name" maxLength={255} name="display_name" onChange={(event) => setConnectionName(event.target.value)} required value={connectionName} />
        </FormField>
        <div className="rounded-md border border-[var(--border)] bg-[var(--bg-panel)] p-3 text-sm leading-5 text-[var(--text-muted)]">
          File bytes are never stored in connection configuration. Uploads use the object-storage boundary after this source is attached to a governed collection.
        </div>
      </form>
      <SetupSubmitFooter created={Boolean(createdId)} form={formId} loading={submitting} />
    </>
  );
}

function SetupIntro({ description }: { description: string }) {
  return <p className="text-sm leading-5 text-[var(--text-muted)]">{description}</p>;
}

function SetupSteps({ labels }: { labels: string[] }) {
  return (
    <ol aria-label="Connection setup steps" className="mt-6 flex flex-wrap gap-x-1 gap-y-2 text-xs text-[var(--text-muted)]">
      {labels.map((label, index) => (
        <li className="inline-flex items-center gap-1" key={label}>
          <span className={cn("inline-flex h-5 w-5 items-center justify-center rounded-full border text-[0.6875rem] font-medium", index === 0 ? "border-[var(--brand-accent)] bg-[var(--brand-accent-soft)] text-[var(--brand-accent)]" : "border-[var(--border)] bg-[var(--surface)]")}>{index + 1}</span>
          <span>{label}</span>{index < labels.length - 1 && <ChevronRight aria-hidden="true" className="ml-0.5 h-3.5 w-3.5 text-[var(--border-strong)]" />}
        </li>
      ))}
    </ol>
  );
}

function SetupSubmitFooter({
  created,
  disabled = false,
  form,
  loading,
}: {
  created: boolean;
  disabled?: boolean;
  form: string;
  loading: boolean;
}) {
  return (
    <div className="mt-6 flex items-center justify-end border-t border-[var(--border)] pt-4">
      <Button disabled={disabled} form={form} icon={created ? <RotateCw aria-hidden="true" className="h-4 w-4" /> : <ArrowRight aria-hidden="true" className="h-4 w-4" />} loading={loading} type="submit">
        {created ? "Retry connection test" : "Connect and validate"}
      </Button>
    </div>
  );
}

function InlineError({ description }: { description: string }) {
  return <div className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{description}</div>;
}

function ConnectionStatus({ label, variant }: { label: string; variant: "default" | "success" | "warning" | "danger" }) {
  return <Badge dot variant={variant}>{label}</Badge>;
}

function connectionPresentation(connection: AdminRow): { label: string; variant: "default" | "success" | "warning" | "danger" } {
  if (connection.status === "active") return { label: "Connected", variant: "success" };
  if (connection.status === "error") return { label: "Error", variant: "danger" };
  if (connection.status === "draft") return { label: "Needs setup", variant: "warning" };
  return { label: titleCase(connection.status || "unknown"), variant: "default" };
}

function connectionScopeSummary(connection: AdminRow) {
  const scopes = configuredScopeLabels(connection.config);
  const scopeLabel = scopes.length === 1 ? scopes[0] : scopes.length ? `${scopes.length} scopes` : "Scope set when bound";
  return `${providerLabel(connection.plugin_key)} · ${scopeLabel}`;
}

function configuredScopeLabels(config: unknown): string[] {
  if (!config || typeof config !== "object") return [];
  const values = config as Record<string, unknown>;
  return [values.space, values.space_key, values.space_keys, values.scopes, values.folder_ids, values.project_keys].flatMap((value) => Array.isArray(value) ? value.map(String) : typeof value === "string" && value.trim() ? [value.trim()] : []);
}

function providerLabel(provider?: string) {
  const connector = connectorDefinition(provider ?? "");
  return connector?.name ?? titleCase(provider ?? "unknown");
}

function titleCase(value: string) {
  return value.replaceAll(/[._-]/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function errorMessage(cause: unknown) {
  return cause instanceof Error ? cause.message : "The Admin request could not be completed.";
}
