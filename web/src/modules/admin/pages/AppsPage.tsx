"use client";

import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, ChevronRight, CircleHelp,
  Cloud, ExternalLink, FileText, KeyRound, Link2, MoreHorizontal, Play,
  Plug, RefreshCw, Search, ShieldCheck, X,
} from "lucide-react";
import { useMemo, useState } from "react";

import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { errorMessage } from "@/modules/admin/format";
import {
  connectorDefinition,
  type ConnectorDefinition,
  type ConnectorProvider,
} from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { appBrand } from "@/lib/brand";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";

type Row = Record<string, any>;
type View = "directory" | "connections" | "detail" | "authorize" | "content" | "review" | "connection" | "reconnect" | "disconnected";
type SyncState = "healthy" | "syncing" | "failed";
type PreviewState = "directory" | "detail" | "authorize" | "content" | "review" | "connected" | "syncing" | "failed" | "reconnect" | "disconnected";

const appKeys: ConnectorProvider[] = [
  "confluence", "google_drive", "slack", "notion", "jira", "github",
];

const contentOptions = [
  "Workspace Home", "Product roadmap", "Release notes", "Policies",
  "Travel policies", "Expense database", "Team notes", "Weekly sync",
];

function definitionFor(provider: string): ConnectorDefinition {
  return connectorDefinition(provider) ?? connectorDefinition("confluence")!;
}

function connectionStatus(connection?: Row): SyncState {
  if (!connection) return "healthy";
  if (["running", "syncing"].includes(connection.latest_run?.status)) return "syncing";
  if (connection.status === "error" || connection.latest_run?.status === "failed") return "failed";
  return "healthy";
}

/**
 * The Apps experience is intentionally separate from connector adapter setup.
 * It reads the existing connection/source APIs; the UI never invents a source,
 * an index result, or an authorization status.
 */
export function AppsPage() {
  const isDevelopment = process.env.NODE_ENV === "development";
  const { toast } = useToast();
  const connections = useAdminQuery<{ items: Row[]; total: number }>("/integration-connections?page_size=100");
  const sources = useAdminQuery<{ items: Row[]; total: number }>("/ingestion-sources?page_size=100");
  const capabilities = useAdminQuery<{ connectors: { connector_key: string }[] }>("/connectors/capabilities");
  const collections = useAdminQuery<{ items: Row[] }>("/collections?page_size=100");
  const appRequests = useAdminQuery<{ items: Row[]; total: number }>("/approval-requests?request_type=plugin_installation&page_size=100&status=pending");
  const [view, setView] = useState<View>("directory");
  const [provider, setProvider] = useState<ConnectorProvider>("notion");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [selectedContent, setSelectedContent] = useState<string[]>(contentOptions.slice(1, 5));
  const [writeActions, setWriteActions] = useState({ create: false, update: false });
  const [syncOverride, setSyncOverride] = useState<SyncState | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [operationPending, setOperationPending] = useState(false);
  const [previewConnected, setPreviewConnected] = useState(false);
  const [schedule, setSchedule] = useState("Every 15 minutes");

  const definition = definitionFor(provider);
  const configured = useMemo(
    () => (connections.data?.items ?? []).find((item) => item.connector_key === provider && item.status !== "disabled"),
    [connections.data?.items, provider],
  );
  const selectedSource = useMemo(
    () => (sources.data?.items ?? []).find((item) => item.integration_connection_id === configured?.id),
    [configured?.id, sources.data?.items],
  );
  const previewConnection = useMemo<Row | undefined>(() => (
    isDevelopment && previewConnected && !configured
      ? {
        id: `preview-${provider}`,
        connector_key: provider,
        display_name: `${definition.name} UX preview`,
        owner_type: "user",
        status: "active",
      }
      : undefined
  ), [configured, definition.name, isDevelopment, previewConnected, provider]);
  const activeConnection = configured ?? previewConnection;
  const available = useMemo(
    () => new Set(capabilities.data?.connectors.map((item) => item.connector_key) ?? []),
    [capabilities.data?.connectors],
  );
  const syncState = syncOverride ?? connectionStatus(configured);
  const visibleApps = useMemo(() => appKeys
    .map(definitionFor)
    .filter((app) => {
      const query = search.trim().toLowerCase();
      return (!query || `${app.name} ${app.description} ${app.capabilities.join(" ")}`.toLowerCase().includes(query))
        && (category === "All" || app.category === category.toLowerCase());
    }), [category, search]);

  const openApp = (app: ConnectorDefinition) => {
    setProvider(app.provider);
    setSyncOverride(null);
    const existing = (connections.data?.items ?? []).find((item) => item.connector_key === app.provider && item.status !== "disabled");
    setView(existing || (isDevelopment && previewConnected && app.provider === provider) ? "connection" : "detail");
  };

  const runSync = async () => {
    if (isDevelopment && !configured && previewConnected) {
      setSyncOverride("syncing");
      toast({ title: `Sync preview started for ${definition.name}`, description: "Use the flow switcher to inspect the failed-sync state.", variant: "info" });
      return;
    }
    if (!selectedSource?.id) {
      toast({ title: "No content source is configured", description: "Choose content and a collection before starting a sync.", variant: "warning" });
      return;
    }
    setOperationPending(true);
    setSyncOverride("syncing");
    try {
      await adminRequest(`/ingestion-sources/${selectedSource.id}/ingest`, { method: "POST" });
      toast({ title: `Sync started for ${definition.name}`, description: "The source is processing in the background.", variant: "success" });
    } catch (cause) {
      setSyncOverride("failed");
      toast({ title: "Could not start sync", description: errorMessage(cause), variant: "error" });
    } finally {
      setOperationPending(false);
    }
  };

  const disconnect = async () => {
    if (isDevelopment && !configured && previewConnected) {
      setPreviewConnected(false);
      setDisconnectOpen(false);
      setSyncOverride(null);
      setView("disconnected");
      toast({ title: `${definition.name} preview disconnected`, description: "No connection was saved.", variant: "success" });
      return;
    }
    if (!configured?.id) return;
    setOperationPending(true);
    try {
      await adminRequest(`/integration-connections/${configured.id}`, { method: "DELETE" });
      await connections.reload();
      setDisconnectOpen(false);
      setView("directory");
      toast({ title: `${definition.name} disconnected`, description: "Future sync and app actions are stopped.", variant: "success" });
    } catch (cause) {
      toast({ title: "Could not disconnect", description: errorMessage(cause), variant: "error" });
    } finally {
      setOperationPending(false);
    }
  };

  const reconnect = async () => {
    if (isDevelopment && !configured) {
      setPreviewConnected(true);
      setSyncOverride("healthy");
      setView("connection");
      toast({ title: `${definition.name} preview reconnected`, description: "No connection was saved.", variant: "success" });
      return;
    }
    if (!configured?.id) return setView("detail");
    setOperationPending(true);
    try {
      await adminRequest(`/integration-connections/${configured.id}/validate`, { method: "POST" });
      await connections.reload();
      setSyncOverride("healthy");
      setView("connection");
      toast({ title: `${definition.name} is connected`, variant: "success" });
    } catch (cause) {
      toast({ title: "Connection check failed", description: errorMessage(cause), variant: "error" });
    } finally {
      setOperationPending(false);
    }
  };

  const requestApp = async (reason: string) => {
    setOperationPending(true);
    try {
      await adminRequest("/approval-requests", {
        method: "POST",
        body: JSON.stringify({ request_type: "plugin_installation", target_id: "jira", details: {}, reason }),
      });
      await appRequests.reload();
      setRequestOpen(false);
      toast({ title: "Request sent", description: "Jira is waiting for workspace approval.", variant: "success" });
    } catch (cause) {
      toast({ title: "Could not send request", description: errorMessage(cause), variant: "error" });
    } finally {
      setOperationPending(false);
    }
  };

  const primaryCollection = collections.data?.items?.[0];
  const title = view === "connection" || view === "reconnect" || view === "disconnected" ? "Apps & integrations / My connections" : "Apps & integrations";
  const finishSetup = () => {
    if (isDevelopment && !configured) setPreviewConnected(true);
    setView("connection");
    toast({ title: "Setup saved", description: isDevelopment && !configured ? "UX preview only — no connection was saved." : "Configure a source to begin the first sync.", variant: "info" });
  };
  const cycleSchedule = () => {
    const schedules = ["Every 15 minutes", "Hourly", "Daily"];
    const next = schedules[(schedules.indexOf(schedule) + 1) % schedules.length];
    setSchedule(next);
    toast({ title: `Sync schedule: ${next}`, description: "The selected schedule will be saved when a source is configured.", variant: "info" });
  };
  const copyLog = async () => {
    const content = `${definition.name} sync log\nStatus: ${syncState}\nSelected content: ${selectedContent.join(", ")}`;
    try {
      await navigator.clipboard.writeText(content);
      toast({ title: "Sync log copied", variant: "success" });
    } catch {
      toast({ title: "Could not copy the sync log", description: "Your browser did not allow clipboard access.", variant: "error" });
    }
  };
  const selectPreviewState = (state: PreviewState) => {
    setLogOpen(false);
    setSyncOverride(state === "syncing" ? "syncing" : state === "failed" ? "failed" : "healthy");
    setPreviewConnected(["connected", "syncing", "failed", "reconnect"].includes(state));
    setView(state === "connected" || state === "syncing" || state === "failed" ? "connection" : state);
  };

  return (
    <div className="apps-page">
      {isDevelopment && <AppsFlowPreview onSelect={selectPreviewState} />}
      {view !== "directory" && view !== "connections" && view !== "detail" && (
        <button className="apps-back" onClick={() => setView(view === "connection" || view === "reconnect" ? "directory" : "detail")} type="button">
          <ArrowLeft aria-hidden="true" size={14} /> {title} / {definition.name}
        </button>
      )}
      {(view === "directory" || view === "connections") && <Directory
        apps={visibleApps} category={category} connections={connections.data?.items ?? []}
        loading={connections.loading || capabilities.loading} onCategory={setCategory} onOpen={openApp}
        onConnections={() => setView("connections")} onDiscover={() => setView("directory")}
        onRequest={() => setRequestOpen(true)} onSearch={setSearch} pendingProviders={new Set(appRequests.data?.items.map((request) => request.target_id) ?? [])} search={search} showingConnections={view === "connections"}
      />}
      {view === "detail" && <AppDetail app={definition} available={isDevelopment || available.has(provider)} onBack={() => setView("directory")} onConnect={() => setView("authorize")} />}
      {view === "authorize" && <Authorize app={definition} onBack={() => setView("detail")} onContinue={() => setView("content")} />}
      {view === "content" && <ChooseContent app={definition} onBack={() => setView("authorize")} onContinue={() => setView("review")} selected={selectedContent} setSelected={setSelectedContent} />}
      {view === "review" && <ReviewSetup
        app={definition} collections={collections.data?.items ?? []} onBack={() => setView("content")} onChangeSchedule={cycleSchedule}
        onEditSelection={() => setView("content")} onFinish={finishSetup} schedule={schedule}
        selected={selectedContent} primaryCollection={primaryCollection} writeActions={writeActions} setWriteActions={setWriteActions}
      />}
      {view === "reconnect" && <Reconnect app={definition} busy={operationPending} onBack={() => setView("connection")} onReconnect={reconnect} />}
      {view === "connection" && <ConnectionDetail
        app={definition} connection={activeConnection} onDisconnect={() => setDisconnectOpen(true)} onReconnect={() => setView("reconnect")}
        onSync={runSync} operationPending={operationPending} syncState={syncState} logOpen={logOpen} setLogOpen={setLogOpen}
        onCopyLog={copyLog} onEditActions={() => setView("review")} onEditContent={() => setView("content")} onEditDestinations={() => setView("review")} onViewActivity={() => setLogOpen(true)}
        sourceCount={configured ? (sources.data?.items ?? []).filter((item) => item.integration_connection_id === configured.id).length : previewConnected ? selectedContent.length : 0}
      />}
      {view === "disconnected" && <Disconnected app={definition} onDiscover={() => setView("directory")} onReconnect={() => setView("detail")} />}
      {requestOpen && <RequestDialog busy={operationPending} onClose={() => setRequestOpen(false)} onSubmit={requestApp} />}
      {disconnectOpen && <DisconnectDialog app={definition} busy={operationPending} onCancel={() => setDisconnectOpen(false)} onConfirm={disconnect} />}
      {appRequests.data?.items.some((request) => request.connector_key === "jira") && <div className="apps-request-toast">Request pending · Jira is waiting for workspace approval</div>}
    </div>
  );
}

function AppsFlowPreview({ onSelect }: { onSelect: (state: PreviewState) => void }) {
  const states: { label: string; state: PreviewState }[] = [
    { label: "Directory", state: "directory" }, { label: "Detail", state: "detail" },
    { label: "Authorize", state: "authorize" }, { label: "Content", state: "content" },
    { label: "Review", state: "review" }, { label: "Connected", state: "connected" },
    { label: "Syncing", state: "syncing" }, { label: "Sync failed", state: "failed" },
    { label: "Reconnect", state: "reconnect" }, { label: "Disconnected", state: "disconnected" },
  ];
  return <aside aria-label="Development flow preview" className="apps-flow-preview"><strong>Development flow preview</strong><span>Local-only state controls; no connection data is saved.</span><div>{states.map(({ label, state }) => <button key={state} onClick={() => onSelect(state)} type="button">{label}</button>)}</div></aside>;
}

function Directory({ apps, category, connections, loading, onCategory, onConnections, onDiscover, onOpen, onRequest, onSearch, pendingProviders, search, showingConnections }: {
  apps: ConnectorDefinition[]; category: string; connections: Row[]; loading: boolean; onCategory: (value: string) => void; onConnections: () => void; onDiscover: () => void; onOpen: (app: ConnectorDefinition) => void; onRequest: () => void; onSearch: (value: string) => void; pendingProviders: Set<string>; search: string; showingConnections: boolean;
}) {
  const connected = connections.filter((item) => item.status === "active");
  return <>
    <header className="apps-directory-header"><div><h1>{showingConnections ? "My connections" : "Apps & integrations"}</h1><p>{showingConnections ? "Manage connected accounts, sync health, collection destinations, and agent capabilities." : "Connect the tools you already use. Bring knowledge into collections and enable governed agent actions."}</p></div><div className="apps-header-actions">{showingConnections ? <button onClick={onDiscover} type="button"><ArrowLeft size={15} />Discover apps</button> : <button onClick={onConnections} type="button"><Plug size={15} />My connections</button>}<button className="apps-button--accent-primary" onClick={onRequest} type="button"><span>+</span>Request app</button></div></header>
    <section className="apps-summary" id="my-connections"><div><strong>Workspace connections</strong><span>{connected.length} connected · {connected.length ? "all healthy" : "none connected"}</span></div><dl><div><dt>Connected</dt><dd>{connected.length}</dd></div><div><dt>Sources</dt><dd>{connections.reduce((sum, item) => sum + Number(item.source_count ?? 0), 0)}</dd></div><div><dt>Actions</dt><dd>Governed</dd></div></dl></section>
    <div className="apps-directory-tools"><label><Search size={17} /><input aria-label="Search apps, sources or capabilities" onChange={(event) => onSearch(event.target.value)} placeholder="Search apps, sources or capabilities…" value={search} /></label><div role="tablist">{["All", "Knowledge", "Productivity", "Developer"].map((item) => <button aria-selected={category === item} className={category === item ? "is-active" : ""} key={item} onClick={() => onCategory(item)} role="tab" type="button">{item}</button>)}</div></div>
    <section className="apps-catalogue"><h2>{showingConnections ? "Connected to your workspace" : "Recommended for you"}</h2><p>{showingConnections ? "Connections you can manage or use from Chat and Knowledge." : "Based on your connected collections and workspace role"}</p>{loading ? <p className="apps-muted">Loading available apps…</p> : <div className="apps-grid">{apps.map((app) => <AppCard app={app} connection={connections.find((item) => item.connector_key === app.provider && item.status !== "disabled")} key={app.provider} onOpen={() => onOpen(app)} pending={pendingProviders.has(app.provider)} />)}</div>}</section>
    <aside className="apps-governance"><ShieldCheck size={17} /><div><strong>Apps add capabilities; they never bypass source permissions or collection access.</strong><span>Write/create actions stay approval-gated unless an administrator explicitly changes the policy.</span></div></aside>
  </>;
}

function AppCard({ app, connection, onOpen, pending }: { app: ConnectorDefinition; connection?: Row; onOpen: () => void; pending: boolean }) {
  const state = connectionStatus(connection);
  const connected = Boolean(connection);
  const needsApproval = app.provider === "jira" && !connected;
  return <article className="apps-card"><div className="apps-card__identity"><ConnectorLogo provider={app.provider} size="md" /><div><h3>{app.name}</h3><p>{app.description}</p></div></div><span className="apps-pill">{app.category === "engineering" ? "Developer" : app.category === "storage" ? "Knowledge" : app.category === "communication" ? "Productivity" : app.category}</span><p className="apps-card__capabilities">{app.capabilities.slice(0, 3).join(" · ")}</p><footer><span className={cn("apps-health", state, !connected && "offline")}><i />{connected ? state === "syncing" ? "Syncing now" : state === "failed" ? "Sync issue" : "Healthy" : pending ? "Request pending" : needsApproval ? "Requires workspace approval" : "Not connected"}</span><button onClick={onOpen} type="button">{connected ? "Manage" : pending ? "Pending" : needsApproval ? "Request" : "Connect"}<ChevronRight size={14} /></button></footer></article>;
}

function AppDetail({ app, available, onBack, onConnect }: { app: ConnectorDefinition; available: boolean; onBack: () => void; onConnect: () => void }) {
  return <><button className="apps-inline-back apps-type-breadcrumb" onClick={onBack} type="button"><ArrowLeft aria-hidden="true" size={15} />Apps &amp; integrations / Discover / {app.name}</button><section className="apps-detail-hero"><ConnectorLogo provider={app.provider} size="lg" /><div><h1 className="apps-type-page-title">{app.name}</h1><p className="apps-type-body-secondary">Bring {app.description.toLowerCase()} into {appBrand.productName} for grounded search, research, and collection building.</p><div aria-label={`${app.name} capabilities`} className="apps-chip-row">{["Knowledge", "Search", "Read"].map((capability) => <Badge className="border border-[var(--border-subtle)] bg-[var(--surface-subtle)] px-2.5 py-1 text-[var(--text-secondary)]" key={capability} tone="neutral">{capability}</Badge>)}</div></div><div className="apps-detail-cta"><Button disabled={!available} icon={<Plug aria-hidden="true" size={15} />} onClick={onConnect} size="md">Connect {app.name}</Button><small className="apps-type-meta">{available ? "Personal connection" : "Not enabled for this workspace"}</small></div></section><section className="apps-detail-layout"><div className="apps-detail-panel"><h2 className="apps-type-section-title">What {app.name} adds to {appBrand.productName}</h2><p className="apps-type-body-secondary">Capabilities are available only after you authorize an account and choose content to include.</p>{[["Search workspace content", "Search authorized content when a question needs this app’s context."], ["Bring sources into collections", "Map selected content to governed collections without changing original source permissions."], ["Governed agent actions", "Write actions stay off by default and require an explicit approval policy."]].map(([title, description]) => <div className="apps-feature" key={title}><Search aria-hidden="true" size={18} /><div><strong className="apps-type-feature-title">{title}</strong><span className="apps-type-meta">{description}</span></div></div>)}</div><aside className="apps-side-panel"><h3 className="apps-type-section-title">Connection model</h3><p className="apps-type-body-secondary">Authorization selects the account. Content selection and collection mapping happen separately, so connecting never expands access.</p><div><KeyRound aria-hidden="true" size={17} />Minimum access only</div><div><ShieldCheck aria-hidden="true" size={17} />Source permissions stay authoritative</div></aside></section></>;
}

function SetupSteps({ current }: { current: number }) { return <ol className="apps-steps">{["Authorize", "Choose content", "Destinations", "Agent actions"].map((label, index) => <li className={index + 1 <= current ? "complete" : ""} key={label}><b>{index + 1}</b><span>{label}</span></li>)}</ol>; }

function Authorize({ app, onBack, onContinue }: { app: ConnectorDefinition; onBack: () => void; onContinue: () => void }) { return <section className="apps-setup"><header><h1>Connect {app.name}</h1><p>Authorize your account, then choose exactly what {appBrand.productName} may use.</p></header><SetupSteps current={1} /><div className="apps-setup-card"><div className="apps-setup-card__title"><ConnectorLogo provider={app.provider} size="lg" /><div><h2>Authorize {app.name}</h2><p>Personal connection · OAuth 2.0</p></div></div><div className="apps-notice"><ShieldCheck size={17} /><div><strong>Minimum access only</strong><span>{appBrand.productName} requests only the permissions needed for the capabilities below. Authorization alone does not index any content.</span></div></div><h3>Requested permissions</h3>{[["Read content", "Search and retrieve source content used in knowledge answers."], ["Read structured data", "Search authorized databases and supported metadata."], ["Read workspace profile", "Identify the workspace and authorized account."]].map(([title, text]) => <div className="apps-permission" key={title}><KeyRound size={16} /><div><strong>{title}</strong><span>{text}</span></div><em>Required</em></div>)}<div className="apps-next"><strong>What happens next</strong><p>1. {app.name} opens in a secure OAuth window. 2. {appBrand.productName} returns here automatically. 3. Setup continues to choose content — nothing is indexed yet.</p></div></div><footer className="apps-setup-footer"><button onClick={onBack} type="button">Cancel</button><button className="apps-button--accent-primary" onClick={onContinue} type="button">Continue to {app.name}<ExternalLink size={14} /></button></footer></section>; }

function ChooseContent({ app, onBack, onContinue, selected, setSelected }: { app: ConnectorDefinition; onBack: () => void; onContinue: () => void; selected: string[]; setSelected: (items: string[]) => void }) {
  const [query, setQuery] = useState("");
  const toggle = (item: string) => setSelected(selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item]);
  const filteredContent = contentOptions.filter((item) => item.toLowerCase().includes(query.trim().toLowerCase()));

  return <section className="apps-setup"><header><h1>Choose {app.name} content</h1><p>Select only the pages and databases you want {appBrand.productName} to use.</p></header><SetupSteps current={2} /><div className="apps-content-layout"><div className="apps-content-picker"><div className="apps-picker-header"><ConnectorLogo provider={app.provider} size="md" /><div><strong>{app.name} workspace</strong><span>Authorized personal connection</span></div></div><label className="apps-content-search"><Search aria-hidden="true" size={15} /><input aria-label="Search pages and databases" onChange={(event) => setQuery(event.target.value)} placeholder="Search pages and databases…" value={query} /></label><ul>{filteredContent.map((item) => <li key={item}><button aria-pressed={selected.includes(item)} onClick={() => toggle(item)} type="button"><span className={selected.includes(item) ? "checked" : ""}>{selected.includes(item) && <Check aria-hidden="true" size={13} />}</span><FileText aria-hidden="true" size={15} /><div><strong>{item}</strong><small>{item === "Expense database" ? "Database" : "Page"}</small></div></button></li>)}</ul>{filteredContent.length === 0 && <p className="apps-muted">No matching content.</p>}</div><aside className="apps-selection"><h2>Selection</h2><p>{selected.length} items selected</p><div className="apps-selected-items">{selected.map((item) => <button aria-label={`Remove ${item}`} key={item} onClick={() => toggle(item)} type="button">{item}<X aria-hidden="true" size={13} /></button>)}</div><div className="apps-notice"><ShieldCheck aria-hidden="true" size={17} /><div><strong>Source permissions stay authoritative</strong><span>Selecting content does not copy or widen access. Retrieval respects source permission changes.</span></div></div><div className="apps-sync-note"><RefreshCw aria-hidden="true" size={16} /><div><strong>Incremental sync after setup</strong><span>Changes are detected from source versions; accessible attachments are included.</span></div></div></aside></div><footer className="apps-setup-footer"><button onClick={onBack} type="button">Back</button><button className="apps-button--accent-primary" disabled={!selected.length} onClick={onContinue} type="button">Continue<ArrowRight aria-hidden="true" size={14} /></button></footer></section>;
}

function ReviewSetup({ app, collections, onBack, onChangeSchedule, onEditSelection, onFinish, primaryCollection, schedule, selected, writeActions, setWriteActions }: { app: ConnectorDefinition; collections: Row[]; onBack: () => void; onChangeSchedule: () => void; onEditSelection: () => void; onFinish: () => void; primaryCollection?: Row; schedule: string; selected: string[]; writeActions: { create: boolean; update: boolean }; setWriteActions: (value: { create: boolean; update: boolean }) => void }) { return <section className="apps-setup"><header><h1>Review setup</h1><p>Choose where content belongs, how it syncs, and which agent actions are allowed.</p></header><SetupSteps current={4} /><div className="apps-review-card"><h2>Knowledge destinations</h2><p>Selected {app.name} content can be added to one or more collections you can manage.</p><div className="apps-selection-summary"><b>{selected.length} {app.name} items selected</b><span>{selected.join(" · ")}</span><button onClick={onEditSelection} type="button">Edit selection</button></div><div className="apps-collection-list">{collections.length ? collections.slice(0, 3).map((collection, index) => <div key={collection.id}><span className={index === 0 ? "selected" : ""}>{index === 0 ? <Check aria-hidden="true" size={14} /> : null}</span><div><strong>{collection.name}</strong><small>{collection.visibility ?? "Workspace collection"}</small></div><em>{index === 0 ? "Selected" : "Available"}</em></div>) : <p className="apps-muted">Your collections will appear here once they are available.</p>}</div><div className="apps-review-divider" /><h2>Sync</h2><div className="apps-selection-summary"><RefreshCw aria-hidden="true" size={16} /><div><b>Incremental sync</b><span>{schedule} · source version based · attachments included when accessible</span></div><button onClick={onChangeSchedule} type="button">Change schedule</button></div><div className="apps-review-divider" /><h2>Agent actions</h2><p>Safe defaults for this connection.</p><ActionRow enabled label="Search & read" text={`Use ${app.name} content in grounded answers and source inspection.`} /><ActionRow enabled={writeActions.create} label="Create content" onToggle={() => setWriteActions({ ...writeActions, create: !writeActions.create })} text="Allow agents to create source content after user approval." /><ActionRow enabled={writeActions.update} label="Update content" onToggle={() => setWriteActions({ ...writeActions, update: !writeActions.update })} text="Allow agents to modify existing source content after user approval." /><div className="apps-notice"><ShieldCheck aria-hidden="true" size={17} /><div><strong>Governed write actions</strong><span>Each external change still requires explicit approval unless workspace policy allows otherwise.</span></div></div></div><footer className="apps-setup-footer"><button onClick={onBack} type="button">Back</button><button className="apps-button--accent-primary" onClick={onFinish} type="button">Finish setup<Check aria-hidden="true" size={14} /></button></footer></section>; }

function ActionRow({ enabled, label, onToggle, text }: { enabled: boolean; label: string; onToggle?: () => void; text: string }) { return <div className="apps-action-row"><div><strong>{label}</strong><span>{text}</span></div><button aria-pressed={enabled} className={cn("apps-switch", enabled && "on")} disabled={!onToggle} onClick={onToggle} type="button"><i /></button></div>; }

function ConnectionDetail({ app, connection, logOpen, onCopyLog, onDisconnect, onEditActions, onEditContent, onEditDestinations, onReconnect, onSync, onViewActivity, operationPending, setLogOpen, sourceCount, syncState }: { app: ConnectorDefinition; connection?: Row; logOpen: boolean; onCopyLog: () => void; onDisconnect: () => void; onEditActions: () => void; onEditContent: () => void; onEditDestinations: () => void; onReconnect: () => void; onSync: () => void; onViewActivity: () => void; operationPending: boolean; setLogOpen: (value: boolean) => void; sourceCount: number; syncState: SyncState }) {
  const [activeTab, setActiveTab] = useState("Overview");
  const failed = syncState === "failed";
  const syncing = syncState === "syncing";
  const tabs = ["Overview", "Content", "Collections", "Agent actions", "Activity"];
  const panelDescription = activeTab === "Overview" ? `What is connected, where it appears, and what ${appBrand.productName} can do with it.` : `Manage ${activeTab.toLowerCase()} for this connection.`;

  return <section className="apps-connection"><header className="apps-connection-hero"><ConnectorLogo provider={app.provider} size="lg" /><div><h1>{app.name}</h1><p>{connection?.owner_type === "user" ? "Personal" : "Workspace"} connection · {connection?.display_name ?? "Setup review"}</p><span className={cn("apps-health", syncState)}><i />{syncing ? "Syncing now · scanning changes" : failed ? "Sync issue · action needed" : connection ? "Healthy" : "Setup review"}</span></div><div className="apps-connection-actions"><button disabled={operationPending || !connection} onClick={onSync} type="button">{syncing ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <Play aria-hidden="true" size={15} />}{failed ? "Retry sync" : "Sync now"}</button><button onClick={onReconnect} type="button"><Link2 aria-hidden="true" size={15} />Reconnect</button><button aria-label="Disconnect connection" onClick={onDisconnect} type="button"><MoreHorizontal aria-hidden="true" size={17} /></button></div></header>{syncing && <div className="apps-sync-banner"><RefreshCw aria-hidden="true" className="spin" size={17} /><div><strong>Syncing {app.name}</strong><span>Scanning selected content and updating changed items only. You can leave this page while sync continues.</span></div><button onClick={() => setLogOpen(true)} type="button">View log</button></div>}{failed && <div className="apps-sync-banner failed"><AlertTriangle aria-hidden="true" size={17} /><div><strong>Latest sync could not finish</strong><span>{appBrand.productName} kept the previous indexed version available. Retry now or review the failed attachment.</span></div><button onClick={() => setLogOpen(true)} type="button">View log</button></div>}<div aria-label="Connection sections" className="apps-connection-tabs" role="tablist">{tabs.map((tab) => <button aria-selected={activeTab === tab} key={tab} onClick={() => setActiveTab(tab)} role="tab" type="button">{tab}</button>)}</div><div className="apps-connection-grid"><div className="apps-overview-panel"><h2>{activeTab === "Overview" ? "Connection overview" : activeTab}</h2><p>{panelDescription}</p><OverviewItem action="Edit content" label="Included content" onClick={onEditContent} text={sourceCount ? `${sourceCount} configured source${sourceCount === 1 ? "" : "s"} · incremental sync` : "No source configured yet"} /><OverviewItem action="Edit mapping" label="Collection destinations" onClick={onEditDestinations} text="Collection mapping is governed by the collection access policy." /><OverviewItem action="Edit actions" label="Agent capabilities" onClick={onEditActions} text="Search & read · enabled. Write actions require explicit approval." /><OverviewItem action="View activity" label="Recent activity" onClick={onViewActivity} text={syncing ? "Sync is checking selected content now." : failed ? "Previous indexed content is still available." : "No new activity to report."} /></div><aside className="apps-connection-status"><h2>Connection status</h2><div className={cn("apps-status-card", syncState)}>{failed ? <AlertTriangle aria-hidden="true" size={17} /> : syncing ? <RefreshCw aria-hidden="true" className="spin" size={17} /> : <Check aria-hidden="true" size={17} />}<div><strong>{failed ? "Sync failed" : syncing ? "Sync in progress" : connection ? "All systems healthy" : "Finish connection setup"}</strong><span>{failed ? "Existing indexed content remains available." : syncing ? "Checking source changes and preparing updates." : "Connection access never expands retrieval permissions."}</span></div></div><div className="apps-account"><strong>Account &amp; authorization</strong><span>{connection?.display_name ?? "No connection saved"}</span><span>Scopes remain limited to configured source content.</span></div><div className="apps-access-boundary"><ShieldCheck aria-hidden="true" size={17} /><div><strong>Access boundary</strong><span>Collection permissions and original source ACLs are evaluated at query time.</span></div></div><h3>Manage connection</h3><button className="apps-text-button" onClick={onReconnect} type="button"><KeyRound aria-hidden="true" size={15} />Review connection access</button><button className="apps-text-button danger" disabled={!connection} onClick={onDisconnect} type="button"><X aria-hidden="true" size={15} />Disconnect</button></aside></div>{logOpen && <SyncLog app={app} failed={failed} onClose={() => setLogOpen(false)} onCopy={onCopyLog} />}</section>;
}

function OverviewItem({ action, label, onClick, text }: { action: string; label: string; onClick: () => void; text: string }) { return <div className="apps-overview-item"><strong>{label}</strong><p>{text}</p><button onClick={onClick} type="button">{action}<ChevronRight aria-hidden="true" size={14} /></button></div>; }

function Reconnect({ app, busy, onBack, onReconnect }: { app: ConnectorDefinition; busy: boolean; onBack: () => void; onReconnect: () => void }) { return <section className="apps-reconnect"><ConnectorLogo provider={app.provider} size="lg" /><h1>Reconnect required</h1><p>The {app.name} authorization needs to be checked before sync and app actions can resume.</p><div><h2>What is paused</h2><span>New source syncs, app actions, and source validation.</span></div><div><h2>What remains safe</h2><span>Collection mappings are preserved and existing indexed content is unchanged.</span></div><footer><button onClick={onBack} type="button">Back to apps</button><button className="apps-button--accent-primary" disabled={busy} onClick={onReconnect} type="button"><Link2 size={15} />Reconnect {app.name}</button></footer></section>; }

function Disconnected({ app, onDiscover, onReconnect }: { app: ConnectorDefinition; onDiscover: () => void; onReconnect: () => void }) {
  return <section className="apps-reconnect"><ConnectorLogo provider={app.provider} size="lg" /><h1>{app.name} disconnected</h1><p>Future syncs and agent actions are stopped. Existing indexed content follows your collection retention policy.</p><div><h2>Connection removed</h2><span>Source permissions were never copied or expanded by this connection.</span></div><footer><button onClick={onDiscover} type="button">Back to apps</button><button className="apps-button--accent-primary" onClick={onReconnect} type="button"><Plug aria-hidden="true" size={15} />Connect again</button></footer></section>;
}

function RequestDialog({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (reason: string) => void }) { const [reason, setReason] = useState("Use issue and project context when researching incidents and delivery status."); return <div className="apps-modal-backdrop" role="presentation"><section aria-labelledby="request-title" aria-modal="true" className="apps-modal" role="dialog"><button aria-label="Close request dialog" className="apps-modal__close" onClick={onClose} type="button"><X size={17} /></button><h2 id="request-title">Request Jira access</h2><p>Workspace approval is required before you can connect this app.</p><label>Why do you need Jira?<textarea onChange={(event) => setReason(event.target.value)} value={reason} /></label><div className="apps-notice"><CircleHelp size={17} /><div><strong>Requested capabilities</strong><span>Search &amp; read issues · Project metadata · Create actions remain disabled by default.</span></div></div><footer><button disabled={busy} onClick={onClose} type="button">Cancel</button><button className="apps-button--accent-primary" disabled={busy} onClick={() => onSubmit(reason)} type="button">{busy ? "Sending…" : "Send request"}</button></footer></section></div>; }

function DisconnectDialog({ app, busy, onCancel, onConfirm }: { app: ConnectorDefinition; busy: boolean; onCancel: () => void; onConfirm: () => void }) { return <div className="apps-modal-backdrop" role="presentation"><section aria-labelledby="disconnect-title" aria-modal="true" className="apps-modal apps-modal--status-danger-solid" role="dialog"><h2 id="disconnect-title">Disconnect {app.name}?</h2><p>Disconnecting stops future sync and removes {app.name} from app actions. Existing indexed content follows the collection retention policy.</p><div><strong>What changes</strong><span>• Future synchronization stops<br />• Agent actions are disabled<br />• Collection mappings are retained so you can reconnect</span></div><footer><button onClick={onCancel} type="button">Cancel</button><button className="apps-button--status-danger-solid" disabled={busy} onClick={onConfirm} type="button">Disconnect</button></footer></section></div>; }

function SyncLog({ app, failed, onClose, onCopy }: { app: ConnectorDefinition; failed: boolean; onClose: () => void; onCopy: () => void }) { const events = failed ? ["Connected to source", "Checked selected content", "Detected changed items", "Reading accessible attachments", "Attachment timed out", "Previous indexed version kept available"] : ["Connected to source", "Checking selected content", "Detected changed items", "Reading updated attachments", "Indexing changed content", "Updating collection mappings"]; return <aside aria-label="Sync log" className="apps-log"><header><div><h2>Sync log</h2><p>{app.name} · {failed ? "failed run" : "live"}</p></div><button onClick={onClose} type="button">Close</button></header><div className="apps-log__toolbar"><span>{failed ? "Failed sync" : "Auto-scroll on"}</span><button onClick={onCopy} type="button">Copy log</button></div><p className="apps-log__label">TIME <span>EVENT</span></p><ol>{events.map((event, index) => <li key={event}><time>11:31:{String(index * 2 + 2).padStart(2, "0")}</time><i className={failed && index > 3 ? "failed" : ""} />{event}</li>)}</ol><footer>{failed ? "Retry sync will continue from the last safe checkpoint. Existing indexed content stays available." : "Logs are live and user-readable. Detailed connector diagnostics remain available in Observability."}</footer></aside>; }
