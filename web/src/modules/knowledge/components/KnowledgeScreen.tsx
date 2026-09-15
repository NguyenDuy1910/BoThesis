"use client";

import { ArrowUpDown, Check, ListFilter, Plus, Upload } from "lucide-react";
import { Fragment, useMemo, useRef, useState } from "react";

import { SplitView } from "@/components/layout/SplitView";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dropdown, DropdownItem, DropdownLabel, DropdownSeparator } from "@/components/ui/Dropdown";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tooltip } from "@/components/ui/Tooltip";
import { useToast } from "@/components/ui/Toast";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { hasSessionPermission } from "@/lib/auth/session";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { authorizeConnection, AuthorizationCancelled, PopupBlocked } from "@/modules/knowledge/authorize";
import { describeConnector, type KnowledgeConnector } from "@/modules/knowledge/connectors";
import {
  connectionsApi,
  sourcesApi,
  type Connection,
} from "@/modules/knowledge/integrations-api";
import { knowledgeActions, useConnections, useConnectorCatalogue, useKnowledge } from "@/modules/knowledge/queries";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

import { ConnectSourceFlow } from "./ConnectSourceFlow";
import { ConnectionDetailView } from "./ConnectionDetailView";
import { ConnectorDetail } from "./ConnectorDetail";
import { DocumentViewer } from "./DocumentViewer";
import { DocumentsView } from "./DocumentsView";
import { KnowledgeScopeSelect, KnowledgeToolbar, knowledgeTabs, type KnowledgeTab } from "./KnowledgeToolbar";
import { SourcesView } from "./SourcesView";
import { SyncActivityView } from "./SyncActivityView";

interface Choice {
  value: string;
  label: string;
}

interface FilterGroup {
  /** The state this group narrows. One group per independent dimension. */
  key: "status" | "type";
  label: string;
  options: readonly Choice[];
}

/**
 * What the two quiet menus offer, per subview.
 *
 * Every subview has both, because the toolbar has to keep its shape: an icon
 * group that changes width between tabs makes the search field slide, and a
 * strip that moves on every click reads as a page reloading. They are not
 * filler — each list narrows or orders the thing that subview actually shows.
 */
const FILTERS: Record<KnowledgeTab, readonly FilterGroup[]> = {
  documents: [
    {
      key: "status",
      label: "Status",
      options: [
        { value: "indexed", label: "Indexed" },
        { value: "indexing", label: "Indexing" },
        { value: "failed", label: "Not indexed" },
        { value: "restricted", label: "Restricted" },
      ],
    },
    {
      key: "type",
      label: "Format",
      options: [
        { value: "pdf", label: "PDF" },
        { value: "document", label: "Documents" },
        { value: "spreadsheet", label: "Spreadsheets" },
        { value: "unsupported", label: "Other formats" },
      ],
    },
  ],
  sources: [
    {
      key: "status",
      label: "Account",
      options: [
        { value: "connected", label: "Healthy" },
        { value: "reauth_required", label: "Reconnect needed" },
        { value: "expired", label: "Access expired" },
        { value: "disconnected", label: "Disconnected" },
      ],
    },
  ],
  activity: [
    {
      key: "status",
      label: "Outcome",
      options: [
        { value: "complete", label: "Completed" },
        { value: "partial", label: "Still running" },
        { value: "failed", label: "Failed" },
      ],
    },
  ],
};

const SORTS: Record<KnowledgeTab, readonly Choice[]> = {
  documents: [
    { value: "recent", label: "Recently updated" },
    { value: "name", label: "Name" },
  ],
  sources: [
    { value: "name", label: "Name" },
    { value: "attention", label: "Needs attention first" },
  ],
  activity: [
    { value: "newest", label: "Newest first" },
    { value: "oldest", label: "Oldest first" },
  ],
};

const DEFAULT_SORT: Record<KnowledgeTab, string> = {
  documents: "recent",
  sources: "name",
  activity: "newest",
};

const SEARCH_COPY: Record<KnowledgeTab, { placeholder: string; label: string }> = {
  documents: { placeholder: "Search documents…", label: "Search documents" },
  sources: { placeholder: "Search accounts…", label: "Search connected accounts" },
  activity: { placeholder: "Search activity…", label: "Search sync activity" },
};

/**
 * Knowledge.
 *
 * One shell, three subviews, and a selection that lives in the address. The
 * rail, the toolbar and the scope stay put whichever subview is showing — only
 * the surface below the toolbar is replaced, which is what makes moving
 * between documents, sources and activity feel like staying in one place.
 */
export function KnowledgeScreen() {
  const query = useKnowledge();
  const catalogue = useConnectorCatalogue();
  // Connections load apart from documents: connecting an account must refresh
  // the accounts list without re-reading every document in the workspace.
  const integrations = useConnections();
  const session = useAuthSession();
  // Shared accounts are administered; a personal one is the member's own. The
  // API enforces this — the interface only avoids offering what it will refuse.
  const canManageWorkspace = hasSessionPermission(session, "source.manage");
  const { toast } = useToast();

  const [tabParam, setTab] = useRouteState("tab", "documents");
  const [selectedId, setSelectedId] = useRouteState("document");
  const [scope, setScope] = useRouteState("scope");
  const [connectionId, setConnectionId] = useRouteState("connection");
  const [connectorKey, setConnectorKey] = useRouteState("connector");

  const [search, setSearch] = useState("");
  const [statusByTab, setStatusByTab] = useState<Record<string, string>>({});
  const [type, setType] = useState("");
  const [sortByTab, setSortByTab] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(false);
  const [selection, setSelection] = useState<string[]>([]);
  const [connecting, setConnecting] = useState<KnowledgeConnector | null>(null);
  /** Set when adding knowledge to an account that is already authorized. */
  const [addingTo, setAddingTo] = useState<Connection | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removalIds, setRemovalIds] = useState<string[] | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const tab = (knowledgeTabs.some((item) => item.id === tabParam) ? tabParam : "documents") as KnowledgeTab;
  const status = statusByTab[tab] ?? "";
  const sort = sortByTab[tab] ?? DEFAULT_SORT[tab];
  const setStatus = (value: string) => setStatusByTab((current) => ({ ...current, [tab]: value }));
  const setSort = (value: string) => setSortByTab((current) => ({ ...current, [tab]: value }));
  const snapshot = query.data;
  const documents = useMemo(() => snapshot?.documents ?? [], [snapshot]);
  const collections = useMemo(() => snapshot?.collections ?? [], [snapshot]);
  // Uploading needs the Collection's identity, not the label in the scope filter.
  const scopeCollectionId = useMemo(
    () => collections.find((collection) => collection.name === scope)?.id ?? null,
    [collections, scope],
  );
  const connections = useMemo(() => integrations.data?.connections ?? [], [integrations.data]);
  const sources = useMemo(() => integrations.data?.sources ?? [], [integrations.data]);
  const runs = useMemo(() => integrations.data?.runs ?? [], [integrations.data]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return documents
      .filter((item) =>
        (!scope || item.collection === scope)
        && (!status || item.state === status)
        && (!type || item.kind === type)
        && item.title.toLowerCase().includes(needle))
      .sort((left, right) => (sort === "name" ? left.title.localeCompare(right.title) : 0));
  }, [documents, scope, search, sort, status, type]);

  const selected = documents.find((item) => item.id === selectedId);
  const selectedConnection = connections.find((item) => item.id === connectionId);
  // Reading about a connector is a state of this subview, not a route of its
  // own: one component introduces every connector, so adding one never adds a
  // page. The key lives in the address so the page can be linked to.
  const selectedEntry = connectorKey
    ? (catalogue.data?.find((entry) => entry.connector.key === connectorKey)
      ?? { connector: describeConnector(connectorKey) })
    : undefined;
  const filtered = Boolean(status || type);

  /**
   * Opening a document is a move from acting on many to reading one, and
   * changing scope is a move to a different set. Both end a selection rather
   * than carrying it into a list where the selected rows are not even visible.
   */
  const openDocument = (document: WorkspaceKnowledgeDocument) => {
    setSelectedId(document.id);
    setSelection([]);
    setExpanded(false);
  };

  const browseCollection = (name: string) => {
    setScope(name);
    setSelection([]);
    setExpanded(false);
  };

  const clearFilters = () => {
    setStatus("");
    setType("");
    setSearch("");
  };


  const act = async (work: () => Promise<void>, failure: string) => {
    setError(null);
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : failure);
    }
  };

  const reindex = (ids: string[]) =>
    act(async () => {
      await Promise.all(ids.map((id) => knowledgeActions.reindex(id)));
      toast({ title: ids.length === 1 ? "Document re-indexed" : `${ids.length} documents re-indexed`, variant: "success" });
    }, "The document could not be re-indexed.");

  const removeDocuments = async () => {
    const ids = removalIds ?? [];
    if (!ids.length) return;
    await act(async () => {
      await Promise.all(ids.map((id) => knowledgeActions.remove(id)));
      setSelection((current) => current.filter((id) => !ids.includes(id)));
      if (selectedId && ids.includes(selectedId)) setSelectedId("");
      toast({
        title: ids.length === 1 ? "Removed from knowledge" : `${ids.length} documents removed`,
        description: "It stops appearing in answers within a minute. The file itself is untouched in its source.",
        variant: "success",
      });
    }, "The document could not be removed.");
    setRemovalIds(null);
  };

  /** Everything that changes connections reloads them, and only them. */
  const connectionAction = (work: () => Promise<void>) =>
    act(async () => {
      await work();
      integrations.reload();
    }, "The connection could not be changed.");

  const reconnect = (connection: Connection) =>
    connectionAction(async () => {
      try {
        await authorizeConnection({
          connectorKey: connection.connector_key,
          ownerType: connection.owner_type,
          connectionId: connection.id,
        });
        toast({
          title: `${connection.display_name} reconnected`,
          description: "Its sources start updating again from the next sync.",
          variant: "success",
        });
      } catch (cause) {
        // Closing the provider window is a decision, not a failure.
        if (cause instanceof AuthorizationCancelled) return;
        if (cause instanceof PopupBlocked) throw new Error(cause.message);
        throw cause;
      }
    });

  const syncConnection = (id: string) => {
    const owned = sources.filter((source) => source.integration_connection_id === id);
    setSyncingId(id);
    return act(async () => {
      await Promise.all(owned.map((source) => sourcesApi.syncNow(source.id)));
      toast({
        title: owned.length === 1 ? "Sync started" : `${owned.length} syncs started`,
        variant: "success",
      });
      integrations.reload();
    }, "The sync could not be started.").finally(() => setSyncingId(null));
  };

  const scopeOptions = [
    { value: "", label: "All knowledge", detail: snapshot ? snapshot.documentCount.toLocaleString() : undefined },
    ...collections.map((collection) => ({
      value: collection.name,
      label: collection.name,
      detail: collection.documentCount.toLocaleString(),
      disabled: collection.restricted,
    })),
  ];

  const pick = (key: FilterGroup["key"], value: string) => {
    if (key === "type") setType(type === value ? "" : value);
    else setStatus(status === value ? "" : value);
  };
  const isPicked = (key: FilterGroup["key"], value: string) =>
    (key === "type" ? type : status) === value;

  /* The same four controls on every subview, so the strip keeps its shape. */
  const toolbarActions = (
    <>
      <Dropdown
        align="right"
        ariaLabel={`Filter ${tab === "activity" ? "activity" : tab}`}
        buttonClassName="knowledge-icon-button"
        label={<ListFilter aria-hidden="true" size={18} />}
        showChevron={false}
        title="Filter"
      >
        {FILTERS[tab].map((group) => (
          <Fragment key={group.key}>
            <DropdownLabel>{group.label}</DropdownLabel>
            {group.options.map((option) => (
              <DropdownItem
                key={option.value}
                onClick={() => pick(group.key, option.value)}
                selected={isPicked(group.key, option.value)}
              >
                <Check
                  aria-hidden="true"
                  className={isPicked(group.key, option.value) ? "h-3.5 w-3.5" : "h-3.5 w-3.5 opacity-0"}
                />
                {option.label}
              </DropdownItem>
            ))}
          </Fragment>
        ))}
        {filtered && (
          <>
            <DropdownSeparator />
            <DropdownItem onClick={clearFilters}>Clear filters</DropdownItem>
          </>
        )}
      </Dropdown>

      <Dropdown
        align="right"
        ariaLabel={`Sort ${tab === "activity" ? "activity" : tab}`}
        buttonClassName="knowledge-icon-button"
        label={<ArrowUpDown aria-hidden="true" size={18} />}
        showChevron={false}
        title="Sort"
      >
        {SORTS[tab].map((option) => (
          <DropdownItem key={option.value} onClick={() => setSort(option.value)} selected={sort === option.value}>
            {option.label}
          </DropdownItem>
        ))}
      </Dropdown>

      {/* Uploading and connecting add to the workspace, not to the subview
          that happens to be open, so both stay available throughout. */}
      <Tooltip label="Upload files" side="bottom">
        <Button
          aria-label="Upload files"
          className="knowledge-icon-button"
          icon={<Upload size={18} />}
          iconOnly
          loading={busy}
          onClick={() => uploadRef.current?.click()}
          variant="ghost"
        />
      </Tooltip>

      <Tooltip label="Connect a source" side="bottom">
        <Button
          aria-label="Connect a source"
          className="knowledge-icon-button"
          icon={<Plus size={18} />}
          iconOnly
          onClick={() => { setTab("sources"); setConnectionId(""); }}
          variant="ghost"
        />
      </Tooltip>
    </>
  );

  const documentsSurface = (
    <SplitView
      detail={selected ? (
        <DocumentViewer
          document={selected}
          expanded={expanded}
          onClose={() => setSelectedId("")}
          onExpand={() => setExpanded((value) => !value)}
          onReindex={() => void reindex([selected.id])}
          onRequestRemove={() => setRemovalIds([selected.id])}
        />
      ) : null}
      list={(
        <DocumentsView
          collections={collections}
          compact={Boolean(selected)}
          documents={rows}
          filtered={filtered}
          loading={query.loading}
          onClearFilters={clearFilters}
          onClearSelection={() => setSelection([])}
          onConnectSource={() => { setTab("sources"); setConnectionId(""); }}
          onOpenCollection={browseCollection}
          onOpenDocument={openDocument}
          onReindexSelection={() => void reindex(selection)}
          onRemoveSelection={() => setRemovalIds(selection)}
          onToggleDocument={(id, checked) =>
            setSelection((current) => checked ? [...new Set([...current, id])] : current.filter((item) => item !== id))}
          onUpload={() => uploadRef.current?.click()}
          onWidenScope={() => setScope("")}
          scope={scope}
          search={search}
          selectedId={selectedId}
          selection={selection}
          totalDocumentCount={snapshot?.documentCount ?? documents.length}
        />
      )}
      mode={selected ? (expanded ? "detail" : "split") : "list"}
    />
  );

  return (
    <section aria-label="Workspace knowledge" className="document-workspace">
      {snapshot && (
        <p className="knowledge-health">
          <span aria-hidden="true" className="knowledge-health__dot" />
          {snapshot.documentCount.toLocaleString()} documents · {connections.length} connected {connections.length === 1 ? "account" : "accounts"} · {sources.length} {sources.length === 1 ? "source" : "sources"}
        </p>
      )}

      <KnowledgeToolbar
        actions={toolbarActions}
        onTabChange={(next) => { setTab(next); setSelection([]); }}
        scope={tab === "documents"
          ? <KnowledgeScopeSelect onChange={(value) => { setScope(value); setSelection([]); }} options={scopeOptions} value={scope} />
          : undefined}
        search={{ value: search, onChange: setSearch, ...SEARCH_COPY[tab] }}
        tab={tab}
      />

      {(query.error || integrations.error || error) && (
        <ErrorState
          actionLabel="Retry"
          className="mx-[var(--page-gutter)] mb-3"
          description={error ?? query.error ?? integrations.error ?? ""}
          layout="inline"
          onAction={() => { setError(null); query.reload(); integrations.reload(); }}
          title="Knowledge action failed"
        />
      )}

      {tab === "documents" && documentsSurface}

      {tab === "sources" && (selectedConnection ? (
        <ConnectionDetailView
          capability={catalogue.data?.find(
            (entry) => entry.connector.key === selectedConnection.connector_key,
          )?.capability}
          connection={selectedConnection}
          onAddKnowledge={() => {
            setAddingTo(selectedConnection);
            setConnecting(describeConnector(selectedConnection.connector_key));
          }}
          onBack={() => setConnectionId("")}
          onDisconnect={() => connectionAction(async () => {
            await connectionsApi.disconnect(selectedConnection.id);
            toast({ title: `${selectedConnection.display_name} disconnected`, variant: "success" });
          })}
          onReconnect={() => reconnect(selectedConnection)}
          onRemove={() => connectionAction(async () => {
            await connectionsApi.remove(selectedConnection.id);
            setConnectionId("");
            toast({ title: "Connection removed", variant: "success" });
          })}
          onRemoveSource={(source) => connectionAction(async () => {
            await sourcesApi.remove(source.id);
            toast({ title: "Source removed", variant: "success" });
          })}
          onSyncSource={(id) => connectionAction(async () => {
            await sourcesApi.syncNow(id);
            toast({ title: "Sync started", variant: "success" });
          })}
          onToggleSource={(source) => connectionAction(async () => {
            await sourcesApi.update(source.id, {
              status: source.status === "paused" ? "ready" : "paused",
            });
          })}
          runs={runs.filter((run) => run.integration_connection_id === selectedConnection.id)}
          sources={sources.filter(
            (source) => source.integration_connection_id === selectedConnection.id,
          )}
        />
      ) : selectedEntry ? (
        <ConnectorDetail
          available={Boolean(
            catalogue.data?.some((entry) => entry.connector.key === selectedEntry.connector.key),
          )}
          capability={selectedEntry.capability}
          connections={connections.filter(
            (connection) => connection.connector_key === selectedEntry.connector.key,
          )}
          connector={selectedEntry.connector}
          onBack={() => setConnectorKey("")}
          onConnect={() => setConnecting(selectedEntry.connector)}
          onOpenConnection={(id) => { setConnectorKey(""); setConnectionId(id); }}
        />
      ) : (
        <SourcesView
          catalogue={catalogue}
          connections={connections}
          live={integrations.data?.live ?? false}
          onAddKnowledge={(connection) => {
            setAddingTo(connection);
            setConnecting(describeConnector(connection.connector_key));
          }}
          onConnect={setConnecting}
          onOpenConnection={setConnectionId}
          onOpenConnector={(connector) => setConnectorKey(connector.key)}
          onReconnect={(connection) => void reconnect(connection)}
          onSync={(id) => void syncConnection(id)}
          search={search}
          sort={sort}
          sources={sources}
          status={status}
          syncingId={syncingId}
        />
      ))}

      {tab === "activity" && (
        <SyncActivityView
          connections={connections}
          runs={runs}
          search={search}
          sort={sort}
          sources={sources}
          status={status}
        />
      )}

      <input
        aria-label="Upload knowledge file"
        className="hidden"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          setBusy(true);
          await act(async () => {
            const target = scopeCollectionId ?? snapshot?.personalCollectionId;
            if (!target) {
              throw new Error("Choose a collection before uploading.");
            }
            await knowledgeActions.upload(file, target);
            toast({ title: "Document uploaded", variant: "success" });
          }, "Upload failed.");
          setBusy(false);
          event.target.value = "";
        }}
        ref={uploadRef}
        type="file"
      />

      <ConnectSourceFlow
        canManageWorkspace={canManageWorkspace}
        capability={catalogue.data?.find((entry) => entry.connector.key === connecting?.key)?.capability}
        connector={connecting}
        existingConnection={addingTo}
        onClose={() => { setConnecting(null); setAddingTo(null); }}
        onConnected={() => { integrations.reload(); query.reload(); }}
        open={Boolean(connecting)}
      />

      <ConfirmDialog
        confirmLabel={removalIds?.length === 1 ? "Remove document" : "Remove documents"}
        description={
          removalIds?.length === 1
            ? "It stops appearing in workspace knowledge and in answers. The file itself is untouched in its source, and re-syncing brings it back unless it is also excluded in Scope."
            : `${removalIds?.length ?? 0} documents stop appearing in workspace knowledge and in answers. The files themselves are untouched in their sources.`
        }
        onClose={() => setRemovalIds(null)}
        onConfirm={removeDocuments}
        open={Boolean(removalIds?.length)}
        title={removalIds?.length === 1 ? "Remove from knowledge?" : "Remove these documents?"}
      />
    </section>
  );
}
