"use client";

import { Plug } from "lucide-react";
import { useMemo, useState } from "react";

import {
  SearchField,
  TableCell,
  TableHeader,
  TableRow,
  type TableColumn,
} from "@/components/patterns";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useConnectorCatalogue } from "@/modules/knowledge/queries";

const COLUMNS: readonly TableColumn[] = [
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
        {loading ? (
          <p role="status">Loading connectors…</p>
        ) : rows.length ? (
          <table className="w-full">
            <TableHeader columns={COLUMNS} />
            <tbody>
              {rows.map((entry) => (
                <TableRow key={entry.connector.key}>
                  <TableCell>{entry.connector.name}</TableCell>
                  <TableCell>
                    {entry.capability?.authentication_type ?? "Not registered here"}
                  </TableCell>
                  <TableCell>
                    <span className="flex flex-wrap gap-1">
                      {(entry.capability?.capabilities ?? []).map((capability) => (
                        <Badge key={capability} tone="neutral">{capability}</Badge>
                      ))}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </tbody>
          </table>
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
