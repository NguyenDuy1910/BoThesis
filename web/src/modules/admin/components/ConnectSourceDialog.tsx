"use client";

import { Link2, Plug } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { adminRequest } from "@/modules/admin/api";
import type {
  IngestionSource,
  IntegrationConnection,
} from "@/modules/admin/collections";
import { errorMessage } from "@/modules/admin/format";
import { connectorDefinition } from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";

/**
 * Points an already-working connection at this collection and starts the first
 * import, so "connect" produces content rather than another configuration step.
 */
export function ConnectSourceDialog({
  collectionId,
  collectionTitle,
  connections,
  error,
  initialConnectionId,
  loading,
  onClose,
  onConnected,
  onReload,
  sources,
}: {
  collectionId: string;
  collectionTitle: string;
  connections: IntegrationConnection[];
  error: string | null;
  initialConnectionId?: string | null;
  loading: boolean;
  onClose: () => void;
  onConnected: () => void;
  onReload: () => void;
  sources: IngestionSource[];
}) {
  const { toast } = useToast();
  const attached = useMemo(
    () => new Set(sources.map((source) => source.integration_connection_id)),
    [sources],
  );
  const available = connections.filter(
    (connection) => connection.status === "active" && !attached.has(connection.id),
  );

  const [selectedId, setSelectedId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedId || !available.length) return;
    const initial = available.find(
      (connection) => connection.id === initialConnectionId,
    );
    setSelectedId(initial?.id ?? available[0].id);
  }, [available, initialConnectionId, selectedId]);

  async function connect() {
    const connection = available.find((candidate) => candidate.id === selectedId);
    if (!connection || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const source = await adminRequest<IngestionSource>(
        `/integration-connections/${connection.id}/sources`,
        {
          method: "POST",
          body: JSON.stringify({
            target_item_id: collectionId,
            display_name: `${collectionTitle} · ${connection.display_name}`,
            config: { scope_mode: "all", include_scopes: [], exclude_scopes: [] },
          }),
        },
      );
      try {
        await adminRequest(`/ingestion-sources/${source.id}/ingest`, {
          method: "POST",
        });
        toast({
          title: `${connection.display_name} connected`,
          description: "The first import has started. Content appears as it arrives.",
          variant: "success",
        });
      } catch (syncError) {
        toast({
          title: `${connection.display_name} connected`,
          description: `The first import did not start: ${errorMessage(syncError)}`,
          variant: "warning",
        });
      }
      onConnected();
    } catch (cause) {
      setSubmitError(errorMessage(cause, "The source could not be connected."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      className="max-w-lg"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <Link
            className="inline-flex h-9 items-center gap-1.5 rounded-[var(--adm-r-sm)] px-2 text-[0.8125rem] font-medium text-[var(--brand-accent)] transition-colors hover:bg-[var(--surface-hover)]"
            href={`/admin/connectors?returnTo=${encodeURIComponent(`/admin/collections/${collectionId}`)}`}
          >
            <Plug aria-hidden="true" className="h-4 w-4" />
            Set up a new connector
          </Link>
          <div className="flex items-center gap-2">
            <Button disabled={submitting} onClick={onClose} variant="secondary">
              Cancel
            </Button>
            <Button
              disabled={!selectedId || !available.length}
              loading={submitting}
              onClick={connect}
            >
              Connect and import
            </Button>
          </div>
        </div>
      }
      onClose={() => {
        if (!submitting) onClose();
      }}
      open
      title="Import from a source"
    >
      <p className="mb-3 text-[0.8125rem] leading-5 text-[var(--text-muted)]">
        Pick a connection you have already set up. Its content starts importing
        into {collectionTitle} right away.
      </p>
      {submitError && (
        <ErrorState className="mb-3" description={submitError} layout="inline" />
      )}

      {loading ? (
        <div aria-busy="true" className="space-y-2">
          {[0, 1, 2].map((index) => (
            <Skeleton className="h-14" key={index} />
          ))}
        </div>
      ) : error ? (
        <ErrorState
          actionLabel="Try again"
          description={error}
          onAction={onReload}
          title="Connections could not be loaded"
        />
      ) : available.length ? (
        <div aria-label="Available connections" className="space-y-1.5" role="radiogroup">
          {available.map((connection, index) => {
            const selected = selectedId === connection.id;
            const connector = connectorDefinition(connection.connector_key);
            return (
              <button
                aria-checked={selected}
                className={cn(
                  "flex w-full items-center gap-3 rounded-[var(--adm-r-md)] px-3 py-2.5 text-left transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                  selected
                    ? "bg-[var(--surface-selected)] shadow-[inset_0_0_0_1px_var(--brand-accent)]"
                    : "shadow-[inset_0_0_0_1px_var(--adm-hairline-strong)] hover:bg-[var(--adm-inset)]",
                )}
                key={connection.id}
                onClick={() => setSelectedId(connection.id)}
                onKeyDown={(event) => {
                  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
                  event.preventDefault();
                  const next =
                    (index + (event.key === "ArrowDown" ? 1 : -1) + available.length) %
                    available.length;
                  setSelectedId(available[next].id);
                  const radios =
                    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                      '[role="radio"]',
                    );
                  radios?.[next]?.focus();
                }}
                role="radio"
                tabIndex={selected ? 0 : -1}
                type="button"
              >
                <ConnectorLogo provider={connection.connector_key} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.8125rem] font-medium text-[var(--text)]">
                    {connection.display_name}
                  </span>
                  <span className="mt-0.5 block truncate text-[0.75rem] text-[var(--text-muted)]">
                    {connector?.name ?? connection.connector_key}
                  </span>
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-4 w-4 shrink-0 rounded-full transition-colors",
                    selected
                      ? "border-[5px] border-[var(--brand-accent)]"
                      : "border-2 border-[var(--adm-hairline-strong)]",
                  )}
                />
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState
          description={
            connections.length
              ? "Every working connection is already importing into this collection."
              : "You have not set up any connections yet. Start with a connector, then come back here."
          }
          icon={<Link2 className="h-5 w-5" />}
          size="md"
          title="Nothing to import from"
        />
      )}
    </Dialog>
  );
}
