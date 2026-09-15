"use client";

import { ChevronRight, Plus, RefreshCw, RotateCcw, TriangleAlert } from "lucide-react";

import { StatusPill } from "@/components/patterns/StatusPill";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Tooltip } from "@/components/ui/Tooltip";
import {
  accountLine,
  byAttention,
  connectionState,
  needsReconnect,
  relativeTime,
} from "@/modules/knowledge/connection-state";
import type { KnowledgeConnector } from "@/modules/knowledge/connectors";
import type { Connection, Source } from "@/modules/knowledge/integrations-api";
import type { ConnectorEntry } from "@/modules/knowledge/queries";

import { AppIcon } from "./AppIcon";
import { ConnectorDirectory } from "./ConnectorDirectory";

/**
 * Connected accounts, then what could be connected next.
 *
 * A row is an *account*, not a source: one Atlassian authorization feeding
 * four spaces is one row here and four rows inside it. That is the whole
 * reason the list stays short as a workspace grows.
 *
 * A healthy account carries no badge. Being listed under "Connected" is
 * already the statement that it works, so a badge is reserved for the ones
 * that need someone.
 */
export function SourcesView({
  connections,
  sources,
  catalogue,
  search,
  status,
  sort,
  onOpenConnection,
  onOpenConnector,
  onConnect,
  onReconnect,
  onAddKnowledge,
  onSync,
  syncingId,
  live,
}: {
  connections: Connection[];
  sources: Source[];
  /** False in the design preview, which has no deployment to connect against. */
  live: boolean;
  /** What this deployment can connect, from its own connector registry. */
  catalogue: {
    data: readonly ConnectorEntry[] | null;
    loading: boolean;
    error: string | null;
    reload: () => void;
  };
  search: string;
  /** Empty shows every connection. */
  status: string;
  sort: string;
  onOpenConnection: (id: string) => void;
  onOpenConnector: (connector: KnowledgeConnector) => void;
  onConnect: (connector: KnowledgeConnector) => void;
  /** The one action that fixes an account nobody can read from any more. */
  onReconnect: (connection: Connection) => void;
  onAddKnowledge: (connection: Connection) => void;
  onSync: (connectionId: string) => void;
  syncingId: string | null;
}) {
  const needle = search.trim().toLowerCase();
  const matched = connections
    .filter((connection) => !status || connection.status === status)
    .filter((connection) =>
      `${connection.display_name} ${connection.connector_key} ${accountLine(connection)}`
        .toLowerCase()
        .includes(needle))
    .sort((left, right) =>
      sort === "attention"
        ? byAttention(left, right)
        : left.display_name.localeCompare(right.display_name));

  const sourceCount = (connection: Connection) =>
    sources.filter((source) => source.integration_connection_id === connection.id).length;

  const lastSynced = (connection: Connection) => {
    const times = sources
      .filter((source) => source.integration_connection_id === connection.id)
      .map((source) => source.last_ingested_at)
      .filter((value): value is string => Boolean(value))
      .sort();
    return times.length ? relativeTime(times[times.length - 1]) : null;
  };

  const broken = connections.filter(needsReconnect);

  return (
    <div className="knowledge-sources">
      {broken.length > 0 && (
        // Stale knowledge is the expensive part of a lapsed grant, and it is
        // invisible: answers keep working, quietly out of date. So the cost is
        // stated before the list, not discovered inside one row of it.
        <div className="knowledge-notice knowledge-notice--danger" role="alert">
          <TriangleAlert aria-hidden="true" size={16} />
          <div>
            <strong>
              {broken.length === 1
                ? `${broken[0].display_name} has stopped updating`
                : `${broken.length} accounts have stopped updating`}
            </strong>
            <p>
              Everything already indexed still answers questions. Anything changed
              since the account lapsed is missing until it is connected again.
            </p>
          </div>
          {broken.length === 1 && (
            <Button onClick={() => onReconnect(broken[0])}>Reconnect</Button>
          )}
        </div>
      )}

      {!live && (
        // Saying this outright is better than an empty list that looks broken.
        // Inventing connections to fill it would be worse than either.
        <p className="knowledge-muted">
          This is the design preview. Connected accounts are read from a running
          deployment, so there are none to show here.
        </p>
      )}

      <section aria-labelledby="connected-sources-heading">
        <div className="knowledge-list-heading">
          <h2 className="knowledge-eyebrow" id="connected-sources-heading">
            Connected accounts
          </h2>
          <span>
            {matched.length === connections.length
              ? `${connections.length} connected`
              : `${matched.length} of ${connections.length}`}
          </span>
        </div>
        {matched.length ? (
          <ul className="knowledge-source-list">
            {matched.map((connection) => {
              const state = connectionState(connection);
              const count = sourceCount(connection);
              const synced = lastSynced(connection);
              return (
                <li key={connection.id}>
                  <button onClick={() => onOpenConnection(connection.id)} type="button">
                    <AppIcon connector={connection.connector_key} size="sm" />
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate">{connection.display_name}</strong>
                      <small className="block truncate">
                        {[
                          accountLine(connection) || null,
                          connection.owner_type === "user" ? "Personal" : null,
                          count ? `${count} ${count === 1 ? "source" : "sources"}` : "No sources yet",
                          synced ? `synced ${synced}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </span>
                    {state.attention && <StatusPill tone={state.tone}>{state.label}</StatusPill>}
                    <ChevronRight aria-hidden="true" size={18} />
                  </button>
                  {/* A lapsed account has exactly one useful action, and syncing
                      is not it. Offering both would invite the one that fails. */}
                  {needsReconnect(connection) ? (
                    <Tooltip label={`Reconnect ${connection.display_name}`} side="top">
                      <Button
                        aria-label={`Reconnect ${connection.display_name}`}
                        icon={<RotateCcw size={16} />}
                        iconOnly
                        onClick={() => onReconnect(connection)}
                        size="sm"
                        variant="ghost"
                      />
                    </Tooltip>
                  ) : (
                    <>
                      <Tooltip label="Add knowledge from this account" side="top">
                        <Button
                          aria-label={`Add knowledge from ${connection.display_name}`}
                          icon={<Plus size={16} />}
                          iconOnly
                          onClick={() => onAddKnowledge(connection)}
                          size="sm"
                          variant="ghost"
                        />
                      </Tooltip>
                      <Tooltip label={`Sync ${connection.display_name}`} side="top">
                        <Button
                          aria-label={`Sync ${connection.display_name}`}
                          disabled={!count}
                          icon={<RefreshCw size={16} />}
                          iconOnly
                          loading={syncingId === connection.id}
                          onClick={() => onSync(connection.id)}
                          size="sm"
                          variant="ghost"
                        />
                      </Tooltip>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState
            description={
              search || status
                ? "No connected account matches the current search and filters."
                : "Connect one below to start building workspace knowledge."
            }
            size="sm"
            title="No connected accounts"
          />
        )}
      </section>

      <ConnectorDirectory
        catalogue={catalogue.data ?? []}
        connectedKeys={connections.map((connection) => connection.connector_key)}
        error={catalogue.error}
        loading={catalogue.loading}
        onConnect={onConnect}
        onOpen={onOpenConnector}
        onRetry={catalogue.reload}
        search={search}
      />
    </div>
  );
}
