"use client";

import { ArrowLeft, Plug, Power, SearchX, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { CardListSkeleton, Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { Tooltip } from "@/components/ui/Tooltip";
import { appBrand } from "@/lib/brand";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { ConnectorSetupDrawer } from "@/modules/admin/components/ConnectorSetupDrawer";
import { errorMessage, pluralize, titleCase } from "@/modules/admin/format";
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

type Row = Record<string, any>;

interface ConnectorCapabilities {
  connectors: { connector_key: string }[];
}

interface Paged {
  items: Row[];
  total: number;
}

function registryStatus(
  connections: Row[],
  providerAvailable: boolean,
): ConnectorRegistryStatus {
  if (connections.some((entry) => ["running", "syncing"].includes(entry.latest_run?.status)))
    return "syncing";
  if (connections.some((entry) => entry.status === "active")) return "connected";
  if (connections.some((entry) => entry.status === "error")) return "failed";
  if (connections.some((entry) => entry.status === "draft")) return "needs_setup";
  if (connections.length && connections.every((entry) => entry.status === "disabled"))
    return "disabled";
  return providerAvailable ? "available" : "unavailable";
}

function safeCollectionReturn(value: string | null) {
  return value && /^\/admin\/collections\/[A-Za-z0-9-]+$/.test(value) ? value : null;
}

export function ConnectorsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = safeCollectionReturn(searchParams.get("returnTo"));

  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<ConnectorCategory | "">("");
  const [selected, setSelected] = useState<ConnectorDefinition | null>(null);
  const [setupKey, setSetupKey] = useState(0);

  const connections = useAdminQuery<Paged>("/integration-connections?page_size=100");
  const capabilities = useAdminQuery<ConnectorCapabilities>("/connectors/capabilities");

  const availableProviders = useMemo(
    () => new Set(capabilities.data?.connectors.map((entry) => entry.connector_key) ?? []),
    [capabilities.data],
  );

  const connectionsByProvider = useMemo(() => {
    const result = new Map<string, Row[]>();
    for (const connection of connections.data?.items ?? []) {
      result.set(connection.connector_key, [
        ...(result.get(connection.connector_key) ?? []),
        connection,
      ]);
    }
    return result;
  }, [connections.data?.items]);

  const catalogue = useMemo<ConnectorSectionItem[]>(() => {
    const term = search.trim().toLocaleLowerCase();
    return connectorDefinitions.flatMap((connector) => {
      const instances = connectionsByProvider.get(connector.provider) ?? [];
      const matchesSearch =
        !term ||
        `${connector.name} ${connector.description} ${connector.category}`
          .toLocaleLowerCase()
          .includes(term);
      const matchesCategory = !category || connector.category === category;
      return matchesSearch && matchesCategory
        ? [
            {
              connector,
              connectionCount: instances.length,
              status: registryStatus(instances, availableProviders.has(connector.provider)),
            },
          ]
        : [];
    });
  }, [availableProviders, category, connectionsByProvider, search]);

  // Grouped by what the administrator can act on right now, not by taxonomy:
  // everything you can set up today, then everything that is coming.
  const readyNow = catalogue.filter((item) => item.status !== "unavailable");
  const notYet = catalogue.filter((item) => item.status === "unavailable");

  const configured = connections.data?.items ?? [];
  const catalogueLoading = capabilities.loading && connections.loading;

  function openSetup(connector: ConnectorDefinition) {
    setSetupKey((value) => value + 1);
    setSelected(connector);
  }

  return (
    <>
      <PageHeader
        actions={
          returnTo && (
            <Link
              className="inline-flex h-9 items-center gap-1.5 rounded-[var(--adm-r-sm)] bg-[var(--adm-surface)] px-3 text-[0.8125rem] font-medium text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--adm-hairline-strong)] transition-colors hover:bg-[var(--adm-inset)] hover:text-[var(--text)]"
              href={returnTo}
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" />
              Back to collection
            </Link>
          )
        }
        description="Connect the systems your teams already work in, then point each one at a collection."
        title="Connectors"
      />

      {/* Configured connections come first: they are the thing being managed.
          The catalogue below is how you add another. */}
      <Card className="mb-6">
        <CardHeader
          description="Each connection can feed one or more collections."
          title="Your connections"
        />
        {connections.loading ? (
          <div className="divide-y divide-[var(--adm-hairline)]">
            {[0, 1].map((index) => (
              <div className="flex items-center gap-3 px-4 py-3" key={index}>
                <Skeleton className="h-8 w-8 rounded-[var(--adm-r-sm)]" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-40" />
                  <Skeleton className="h-2.5 w-28" />
                </div>
                <Skeleton className="h-5 w-20" />
              </div>
            ))}
          </div>
        ) : connections.error ? (
          <ErrorState
            actionLabel="Try again"
            description={connections.error}
            layout="inline"
            onAction={connections.reload}
          />
        ) : configured.length === 0 ? (
          <EmptyState
            description="Pick a connector below to set up your first one. Uploading files directly to a collection works without any connector."
            icon={<Plug className="h-5 w-5" />}
            size="md"
            title="Nothing connected yet"
          />
        ) : (
          <ul className="divide-y divide-[var(--adm-hairline)]">
            {configured.map((connection) => (
              <ConnectionRow
                connection={connection}
                key={connection.id}
                onChanged={connections.reload}
                onManage={() => {
                  const definition = connectorDefinition(connection.connector_key);
                  if (definition) openSetup(definition);
                }}
              />
            ))}
          </ul>
        )}
      </Card>

      <section aria-labelledby="connector-catalogue">
        <div className="adm-toolbar">
          <h2
            className="text-[0.9375rem] font-semibold text-[var(--text)]"
            id="connector-catalogue"
          >
            Add a connector
          </h2>
          <div className="adm-toolbar__spacer" />
          <SearchInput
            ariaLabel="Search connectors"
            className="w-full sm:w-64"
            debounceMs={0}
            onChange={setSearch}
            placeholder="Search connectors…"
            value={search}
          />
          <Select
            aria-label="Filter connectors by category"
            className="w-full sm:w-44"
            onChange={(event) =>
              setCategory(event.target.value as ConnectorCategory | "")
            }
            options={[
              { value: "", label: "All categories" },
              ...connectorCategories.map((entry) => ({
                value: entry.id,
                label: entry.label,
              })),
            ]}
            value={category}
          />
        </div>

        {catalogueLoading ? (
          <CardListSkeleton count={6} />
        ) : catalogue.length === 0 ? (
          <Card>
            <EmptyState
              action={
                <Button
                  onClick={() => {
                    setSearch("");
                    setCategory("");
                  }}
                  variant="secondary"
                >
                  Clear filters
                </Button>
              }
              description="No connector matches that search. Try a different name or category."
              icon={<SearchX className="h-5 w-5" />}
              title="Nothing matches"
            />
          </Card>
        ) : (
          <div className="space-y-7">
            {readyNow.length > 0 && (
              <ConnectorSection
                description="Available in this deployment — you can set these up now."
                items={readyNow}
                onSelect={openSetup}
                title="Ready to connect"
              />
            )}
            {notYet.length > 0 && (
              <ConnectorSection
                description={`Supported by ${appBrand.productName} but not enabled here yet. Ask your platform team to turn one on.`}
                items={notYet}
                onSelect={openSetup}
                title="Not available yet"
              />
            )}
          </div>
        )}
      </section>

      {selected && (
        <ConnectorSetupDrawer
          available={availableProviders.has(selected.provider)}
          capabilityError={capabilities.error}
          capabilityLoading={capabilities.loading}
          connections={connectionsByProvider.get(selected.provider) ?? []}
          connector={selected}
          key={setupKey}
          onChanged={connections.reload}
          onClose={() => setSelected(null)}
          onCreated={(connectionId) => {
            connections.reload();
            setSelected(null);
            if (returnTo && connectionId) {
              router.push(`${returnTo}?connect=${encodeURIComponent(connectionId)}`);
            }
          }}
        />
      )}
    </>
  );
}

function scopeSummary(connection: Row) {
  const config = connection.config;
  if (!config || typeof config !== "object") return "Whole workspace";
  const values = config as Record<string, unknown>;
  const scopes = [
    values.space,
    values.space_key,
    values.space_keys,
    values.scopes,
    values.folder_ids,
    values.project_keys,
  ].flatMap((value) =>
    Array.isArray(value)
      ? value.map(String)
      : typeof value === "string" && value.trim()
        ? [value.trim()]
        : [],
  );
  if (!scopes.length) return "Whole workspace";
  return scopes.length === 1 ? scopes[0] : `${scopes.length} areas`;
}

function ConnectionRow({
  connection,
  onChanged,
  onManage,
}: {
  connection: Row;
  onChanged: () => void;
  onManage: () => void;
}) {
  const { toast } = useToast();
  const [pending, setPending] = useState<"test" | "toggle" | null>(null);
  const [removing, setRemoving] = useState(false);
  const definition = connectorDefinition(connection.connector_key);

  async function run(action: "test" | "toggle") {
    setPending(action);
    try {
      if (action === "test") {
        await adminRequest(`/integration-connections/${connection.id}/validate`, {
          method: "POST",
        });
        toast({
          title: "Connection works",
          description: "It can reach the source with the credentials you saved.",
          variant: "success",
        });
      } else {
        const disabling = connection.status !== "disabled";
        await adminRequest(`/integration-connections/${connection.id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: disabling ? "disabled" : "active" }),
        });
        toast({
          title: disabling ? "Connection paused" : "Connection resumed",
          variant: "success",
        });
      }
      onChanged();
    } catch (cause) {
      toast({
        title: action === "test" ? "Connection test failed" : "Could not change status",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setPending(null);
    }
  }

  async function remove() {
    await adminRequest(`/integration-connections/${connection.id}`, {
      method: "DELETE",
    }).catch((cause) => {
      throw new Error(errorMessage(cause, "The connection could not be removed."));
    });
    toast({ title: "Connection removed", variant: "success" });
    setRemoving(false);
    onChanged();
  }

  const paused = connection.status === "disabled";

  return (
    <li className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
      <ConnectorLogo provider={String(connection.connector_key)} size="sm" />
      <button
        className="min-w-0 flex-1 text-left"
        onClick={onManage}
        type="button"
      >
        <span className="block truncate text-[0.8125rem] font-medium text-[var(--text)]">
          {connection.display_name}
        </span>
        <span className="mt-0.5 block truncate text-[0.75rem] text-[var(--text-muted)]">
          {definition?.name ?? titleCase(connection.connector_key)} ·{" "}
          {scopeSummary(connection)} ·{" "}
          {pluralize(connection.source_count ?? 0, "collection")}
        </span>
      </button>
      <div className="flex shrink-0 items-center gap-1.5">
        <StatusBadge status={connection.status} />
        <Tooltip label="Check this connection still works" side="top">
          <Button
            aria-label={`Test ${connection.display_name}`}
            icon={<ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />}
            iconOnly
            loading={pending === "test"}
            onClick={() => run("test")}
            size="sm"
            variant="ghost"
          />
        </Tooltip>
        <Tooltip label={paused ? "Resume syncing" : "Pause syncing"} side="top">
          <Button
            aria-label={paused ? "Resume this connection" : "Pause this connection"}
            icon={<Power aria-hidden="true" className="h-3.5 w-3.5" />}
            iconOnly
            loading={pending === "toggle"}
            onClick={() => run("toggle")}
            size="sm"
            variant="ghost"
          />
        </Tooltip>
        <Tooltip label="Remove connection" side="top">
          <Button
            aria-label={`Remove ${connection.display_name}`}
            icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />}
            iconOnly
            onClick={() => setRemoving(true)}
            size="sm"
            variant="ghost"
          />
        </Tooltip>
      </div>

      <ConfirmDialog
        confirmLabel="Remove connection"
        description={
          <>
            <strong className="font-semibold text-[var(--text)]">
              {connection.display_name}
            </strong>{" "}
            will stop importing. Content already indexed stays searchable until you
            remove it from its collection.
          </>
        }
        onClose={() => setRemoving(false)}
        onConfirm={remove}
        open={removing}
        title="Remove this connection?"
      />
    </li>
  );
}
