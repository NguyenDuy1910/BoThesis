"use client";

import {
  FilePlus2,
  Import,
  Link2,
  Plus,
  Plug,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { adminRequest } from "@/modules/admin/api";
import { connectorDefinition } from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { errorMessage } from "@/modules/knowledge-management/presentation";
import type { IngestionSource, IntegrationConnection } from "@/modules/knowledge-management/types";

export function AddContentMenu({
  onConnect,
  onConnectNew,
  onManual,
  onUpload,
}: {
  onConnect: () => void;
  onConnectNew: () => void;
  onManual: () => void;
  onUpload: () => void;
}) {
  return (
    <Dropdown
      ariaLabel="Add content"
      buttonClassName="h-10 border-[var(--primary)] bg-[var(--primary)] text-[var(--text-on-brand)] hover:border-[var(--primary-hover)] hover:bg-[var(--primary-hover)] hover:text-[var(--text-on-brand)] active:bg-[var(--primary-pressed)]"
      label={<><Plus aria-hidden="true" className="h-4 w-4" />Add content</>}
      menuClassName="w-64"
    >
      <DropdownItem onClick={onUpload}>
        <Upload aria-hidden="true" className="h-4 w-4" />
        Upload files
      </DropdownItem>
      <DropdownItem onClick={onManual}>
        <FilePlus2 aria-hidden="true" className="h-4 w-4" />
        Create an item manually
      </DropdownItem>
      <DropdownItem onClick={onConnect}>
        <Import aria-hidden="true" className="h-4 w-4" />
        Import from a connected source
      </DropdownItem>
      <DropdownItem onClick={onConnectNew}>
        <Plug aria-hidden="true" className="h-4 w-4" />
        Connect a new source
      </DropdownItem>
    </Dropdown>
  );
}

export function ConnectSourceDialog({
  sources,
  connections,
  error,
  initialConnectionId,
  knowledgeBaseId,
  knowledgeBaseTitle,
  loading,
  onClose,
  onConnected,
  onReload,
}: {
  sources: IngestionSource[];
  connections: IntegrationConnection[];
  error: string | null;
  initialConnectionId?: string | null;
  knowledgeBaseId: string;
  knowledgeBaseTitle: string;
  loading: boolean;
  onClose: () => void;
  onConnected: () => void;
  onReload: () => void;
}) {
  const { toast } = useToast();
  const existingConnectionIds = useMemo(
    () => new Set(sources.map((source) => source.integration_connection_id)),
    [sources],
  );
  const available = connections.filter(
    (connection) => connection.status === "active" && !existingConnectionIds.has(connection.id),
  );
  const [selectedId, setSelectedId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const returnPath = `/admin/knowledge-bases/${knowledgeBaseId}`;

  useEffect(() => {
    if (selectedId || !available.length) return;
    const initial = available.find((connection) => connection.id === initialConnectionId);
    setSelectedId(initial?.id ?? (available.length === 1 ? available[0].id : ""));
  }, [available, initialConnectionId, selectedId]);

  async function connect() {
    if (!selectedId || submitting) return;
    const connection = available.find((candidate) => candidate.id === selectedId);
    if (!connection) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const source = await adminRequest<IngestionSource>(
        `/integration-connections/${connection.id}/sources`,
        {
          method: "POST",
          body: JSON.stringify({
            target_item_id: knowledgeBaseId,
            display_name: `${knowledgeBaseTitle} · ${connection.display_name}`,
            config: {
              scope_mode: "all",
              include_scopes: [],
              exclude_scopes: [],
            },
          }),
        },
      );
      try {
        await adminRequest(`/ingestion-sources/${source.id}/ingest`, { method: "POST" });
        toast({
          title: "Source connected",
          description: `${connection.display_name} is connected and the first import is queued.`,
          variant: "success",
        });
      } catch (syncError) {
        toast({
          title: "Source connected",
          description: `The connection was saved, but the first import could not start: ${errorMessage(syncError)}`,
          variant: "info",
        });
      }
      onConnected();
    } catch (cause) {
      setSubmitError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      className="max-w-2xl"
      footer={(
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <Link
            className="inline-flex min-h-10 items-center gap-2 rounded-md px-2 text-sm font-medium text-[var(--brand-accent)] hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            href={`/admin/sources?returnTo=${encodeURIComponent(returnPath)}`}
          >
            <Plug aria-hidden="true" className="h-4 w-4" />
            Connect a new source
          </Link>
          <div className="flex items-center gap-2">
            <Button disabled={submitting} onClick={onClose} variant="secondary">Cancel</Button>
            <Button disabled={!selectedId} loading={submitting} onClick={connect}>Connect and import</Button>
          </div>
        </div>
      )}
      onClose={() => { if (!submitting) onClose(); }}
      open
      title="Connect a source"
    >
      <p className="mb-4 text-sm leading-6 text-[var(--text-muted)]">
        Choose an existing validated connection. Its saved source scope will be
        attached to this knowledge base and the first import will start now.
      </p>
      {submitError && <p className="mb-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{submitError}</p>}
      {loading ? (
        <div aria-busy="true" aria-label="Loading connected sources" className="space-y-2">
          {[0, 1, 2].map((index) => <Skeleton className="h-16" key={index} />)}
        </div>
      ) : error ? (
        <ErrorState actionLabel="Retry" description={error} onAction={onReload} title="Connected sources are unavailable" />
      ) : available.length ? (
        <div aria-label="Connected sources" className="space-y-2" role="radiogroup">
          {available.map((connection) => {
            const selected = selectedId === connection.id;
            const connector = connectorDefinition(connection.connector_key);
            return (
              <button
                aria-checked={selected}
                className={cn("knowledge-source-choice", selected && "is-selected")}
                key={connection.id}
                onClick={() => setSelectedId(connection.id)}
                onKeyDown={(event) => {
                  if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
                  event.preventDefault();
                  const radios = Array.from(event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? []);
                  const current = radios.indexOf(event.currentTarget);
                  const next = event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? radios.length - 1
                      : (current + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + radios.length) % radios.length;
                  const target = available[next];
                  if (target) setSelectedId(target.id);
                  radios[next]?.focus();
                }}
                role="radio"
                tabIndex={selected || (!selectedId && connection === available[0]) ? 0 : -1}
                type="button"
              >
                <ConnectorLogo provider={connection.connector_key} size="sm" />
                <span className="min-w-0 flex-1 text-left">
                  <strong className="block truncate text-sm text-[var(--text)]">{connection.display_name}</strong>
                  <small className="mt-0.5 block truncate text-xs text-[var(--text-muted)]">{connector?.name ?? connection.connector_key} · Validated connection</small>
                </span>
                <span aria-hidden="true" className="knowledge-source-choice__radio" />
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState
          description="Every active connection is already attached here, or this workspace has no validated connections yet."
          icon={<Link2 className="h-5 w-5" />}
          size="md"
          title="No sources available to connect"
        />
      )}
    </Dialog>
  );
}

export function DeferredContentDialog({
  onClose,
}: {
  onClose: () => void;
}) {
  return (
    <Dialog
      footer={<Button onClick={onClose}>Close</Button>}
      onClose={onClose}
      open
      title="Create an item manually"
    >
      <div className="knowledge-capability-note">
        <FilePlus2 aria-hidden="true" />
        <div>
          <h3>Manual item creation is not available yet</h3>
          <p>
            The backend does not yet expose a governed collection-scoped endpoint for authored content, lineage, and indexing. No draft or fake item has been created.
          </p>
        </div>
      </div>
    </Dialog>
  );
}
