"use client";

import { Plus } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import type { KnowledgeConnector } from "@/modules/knowledge/connectors";
import type { ConnectorEntry } from "@/modules/knowledge/queries";

import { AppIcon } from "./AppIcon";

/**
 * What this workspace could connect next.
 *
 * It reads as an app directory rather than an admin table: a mark, a name, one
 * phrase saying what it brings in, and a quiet plus. Nothing is boxed, because
 * fifteen cards would turn a browsable list into a wall.
 *
 * A connector already in use stays listed. Connections are per account, so a
 * second Google Drive or a second Atlassian site is a normal thing to add, and
 * hiding the row would make it look impossible.
 */
export function ConnectorDirectory({
  /** What the deployment's connector registry supports, already described. */
  catalogue,
  loading,
  error,
  onRetry,
  /** Keys already connected. They are not offered a second time. */
  connectedKeys,
  search,
  onOpen,
  onConnect,
}: {
  catalogue: readonly ConnectorEntry[];
  loading: boolean;
  /** The registry could not be read. Not the same thing as an empty registry. */
  error: string | null;
  onRetry: () => void;
  connectedKeys: readonly string[];
  search: string;
  /** Reading about a connector before committing to one. */
  onOpen: (connector: KnowledgeConnector) => void;
  /** The fast path, for someone who already knows what they are adding. */
  onConnect: (connector: KnowledgeConnector) => void;
}) {
  const needle = search.trim().toLowerCase();
  const available = catalogue.filter(({ connector }) =>
    `${connector.name} ${connector.description}`.toLowerCase().includes(needle));
  const isConnected = (key: string) => connectedKeys.includes(key);

  return (
    <section aria-labelledby="available-connectors-heading">
      <div className="knowledge-list-heading">
        <h2 className="knowledge-eyebrow" id="available-connectors-heading">Available connectors</h2>
        {!loading && !error && <span>{available.length} available</span>}
      </div>
      {error ? (
        <ErrorState
          actionLabel="Try again"
          description={error}
          layout="inline"
          onAction={onRetry}
          title="This deployment's connectors could not be read"
        />
      ) : loading ? (
        <div aria-busy="true" className="knowledge-connectors">
          <span className="sr-only">Loading connectors</span>
          {Array.from({ length: 6 }).map((_, index) => (
            <div className="knowledge-connectors__skeleton" key={index}>
              <Skeleton className="h-10 w-10 rounded-[var(--radius-sm)]" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <Skeleton className="h-3 w-[34%]" />
                <Skeleton className="h-2.5 w-[58%]" />
              </div>
            </div>
          ))}
        </div>
      ) : available.length ? (
        <div className="knowledge-connectors">
          {available.map(({ connector, capability }) => {
            // A connector whose OAuth client this deployment never configured
            // cannot be connected. Offering the button anyway would send the
            // reader through a consent screen that ends in an error.
            const connectable = capability?.available ?? true;
            return (
              <div className="knowledge-connectors__item" key={connector.key}>
                <button
                  className="knowledge-connectors__open"
                  onClick={() => onOpen(connector)}
                  type="button"
                >
                  <AppIcon connector={connector.key} />
                  <span className="min-w-0 flex-1">
                    <strong>{connector.name}</strong>
                    <small>
                      {!connectable
                        ? "Not configured on this deployment"
                        : isConnected(connector.key)
                          ? `Connected · ${connector.description}`
                          : connector.description}
                    </small>
                  </span>
                </button>
                {connectable && (
                  <button
                    aria-label={
                      isConnected(connector.key)
                        ? `Connect another ${connector.name} account`
                        : `Connect ${connector.name}`
                    }
                    className="knowledge-connectors__add"
                    onClick={() => onConnect(connector)}
                    type="button"
                  >
                    <Plus aria-hidden="true" size={18} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyState
          description={
            search
              ? "No connector on this deployment matches this search."
              : "This deployment has no connectors registered."
          }
          size="sm"
          title="Nothing to add"
        />
      )}
    </section>
  );
}
