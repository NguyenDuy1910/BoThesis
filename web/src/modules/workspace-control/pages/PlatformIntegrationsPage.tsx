"use client";

import { Plug } from "lucide-react";
import { useMemo, useState } from "react";

import { SearchField } from "@/components/patterns";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useConnectorCatalogue } from "@/modules/knowledge/queries";
import { ControlPlaneLoadingSkeleton } from "@/modules/workspace-control/components/ControlPlaneLoadingSkeleton";

const COLUMNS = [
  { id: "connector", label: "Connector" },
  { id: "authentication", label: "Authorization", width: 180 },
  { id: "capabilities", label: "Capabilities" },
];

/**
 * What this deployment can connect.
 *
 * The registry is the authority: a connector appears here because the running
 * backend implements it, not because a catalogue lists it. Turning a connector
 * on or off per workspace is a policy no endpoint stores yet, so the table
 * reports availability rather than offering a switch that would not hold.
 */
export function PlatformIntegrationsPage() {
  const { data, error, loading, reload } = useConnectorCatalogue();
  const [search, setSearch] = useState("");
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data ?? []).filter((entry) =>
      !term || entry.connector.name.toLowerCase().includes(term),
    );
  }, [data, search]);

  if (error) {
    return <ErrorState description={error} onAction={reload} title="Connectors could not be loaded" />;
  }

  if (loading && !data) return <ControlPlaneLoadingSkeleton variant="integrations" />;

  return (
    <Card>
      <CardHeader
        description="Connectors this deployment implements. Each workspace authorizes its own accounts in Knowledge → Sources."
        title="Available connectors"
      />
      <CardBody className="grid gap-3">
        <SearchField
          onChange={setSearch}
          placeholder="Search connectors…"
          value={search}
        />
        {rows.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[42rem] text-left">
              <thead className="border-b border-[var(--border-subtle)]">
                <tr>
                  {COLUMNS.map((column) => (
                    <th
                      className="px-3.5 pb-2.5 text-[length:var(--text-size-caption)] font-medium uppercase tracking-[var(--text-tracking-caption)] text-[var(--text-tertiary)]"
                      key={column.id}
                      scope="col"
                      style={column.width === undefined ? undefined : { width: column.width }}
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => {
                  const capabilities = entry.capability?.capabilities ?? [];
                  return (
                    <tr
                      className="border-b border-[var(--border-subtle)] last:border-b-0 hover:bg-[var(--surface-hover)]"
                      key={entry.connector.key}
                    >
                      <td className="px-3.5 py-2.5 font-medium text-[var(--text-primary)]">
                        {entry.connector.name}
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-secondary)]">
                        {entry.capability?.authentication_type ?? "Not registered here"}
                      </td>
                      <td className="px-3.5 py-2.5 text-[var(--text-secondary)]">
                        {capabilities.length ? (
                          <span className="flex flex-wrap gap-1">
                            {capabilities.map((capability) => (
                              <Badge key={capability} tone="neutral">{capability}</Badge>
                            ))}
                          </span>
                        ) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            description="This deployment registers no connectors, or the search matched none."
            icon={<Plug size={20} />}
            title="No connectors"
          />
        )}
      </CardBody>
    </Card>
  );
}
