"use client";

import { Plug } from "lucide-react";
import { useMemo, useState } from "react";

import {
  SearchField,
  StatusPill,
  TableCell,
  TableHeader,
  TableRow,
  Toggle,
  type StatusTone,
  type TableColumn,
} from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Dialog } from "@/components/ui/Dialog";
import { Tabs } from "@/components/ui/Tabs";
import {
  type ConnectorAvailability,
  type PlatformConnection,
} from "@/modules/admin/fixtures";
import { adminData, useAdminData } from "@/modules/admin/queries";

const STATUS: Record<PlatformConnection["status"], { label: string; tone: StatusTone }> = {
  healthy: { label: "Healthy", tone: "success" },
  syncing: { label: "Syncing", tone: "info" },
  failed: { label: "Failed", tone: "danger" },
  paused: { label: "Paused", tone: "neutral" },
};

const CONNECTOR_COLUMNS: readonly TableColumn[] = [
  { id: "connector", label: "Connector" },
  { id: "category", label: "Category", width: 150 },
  { id: "connections", label: "Connections", width: 120 },
  { id: "available", label: "Available", width: 100 },
];

const CONNECTION_COLUMNS: readonly TableColumn[] = [
  { id: "connector", label: "Connector", width: 160 },
  { id: "tenant", label: "Tenant", width: 180 },
  { id: "scope", label: "Scope" },
  { id: "status", label: "Status", width: 110 },
  { id: "sync", label: "Last sync", width: 140 },
];

/**
 * Two questions, kept apart: which connectors tenants may use at all, and what
 * is actually running right now. A failing connection is a tenant's problem to
 * fix, but it is visible here because the connector itself may be the cause.
 */
export function PlatformIntegrationsPage() {
  const [tab, setTab] = useState("catalogue");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<PlatformConnection | null>(null);
  const connectorQuery = useAdminData(adminData.platform.integrations);
  const connectionQuery = useAdminData(adminData.platform.connections);
  const connectors: ConnectorAvailability[] = connectorQuery.data ?? [];
  const connectionRows: PlatformConnection[] = connectionQuery.data ?? [];

  const failing = connectionRows.filter((row) => row.status === "failed").length;

  const connections = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return connectionRows;
    return connectionRows.filter((row) =>
      `${row.connector} ${row.tenant} ${row.scope}`.toLowerCase().includes(term),
    );
  }, [connectionRows, query]);

  return (
    <>
      <Tabs
        activeTab={tab}
        ariaLabel="Integration views"
        className="mb-4"
        onChange={setTab}
        tabs={[
          { id: "catalogue", label: "Catalogue", count: connectors.filter((row) => row.available).length },
          { id: "connections", label: "Connections", count: connectionRows.length },
        ]}
      />

      {tab === "catalogue" ? (
        <Card>
          <CardHeader
            description="A connector that is off cannot be connected by any tenant. Existing connections stop syncing and say why."
            title="Connector availability"
          />
          <CardBody className="px-0 pb-0">
            <TableHeader columns={CONNECTOR_COLUMNS} />
            {connectors.map((connector) => (
              <TableRow key={connector.id}>
                <TableCell className="font-medium text-[var(--text-primary)]">{connector.name}</TableCell>
                <TableCell width={150}>{connector.category}</TableCell>
                <TableCell width={120}>
                  {connector.connections === 0 ? "—" : connector.connections.toLocaleString()}
                </TableCell>
                <TableCell width={100}>
                  <Toggle
                    checked={connector.available}
                    label={`${connector.available ? "Disable" : "Enable"} ${connector.name}`}
                    onChange={() => void adminData.platform.saveIntegrations(connectors.map((row) =>
                      row.id === connector.id ? { ...row, available: !row.available } : row,
                    ))}
                  />
                </TableCell>
              </TableRow>
            ))}
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader
            actions={
              <SearchField
                className="w-full sm:w-64"
                onChange={setQuery}
                placeholder="Search connections…"
                value={query}
              />
            }
            description={
              failing
                ? `${failing} connection${failing === 1 ? "" : "s"} failing. The owning tenant sees the same failure in its own Knowledge section.`
                : "Every connection is syncing normally."
            }
            title="Running connections"
          />
          <CardBody className="px-0 pb-0">
            {connections.length === 0 ? (
              <EmptyState
                description="No connection matches that search."
                icon={<Plug className="h-5 w-5" />}
                title="Nothing found"
              />
            ) : (
              <>
                <TableHeader columns={CONNECTION_COLUMNS} />
                {connections.map((connection) => (
                  <TableRow
                    actions={
                      connection.status === "failed" ? (
                        <Button size="sm" variant="ghost" onClick={() => setSelected(connection)}>
                          Inspect
                        </Button>
                      ) : undefined
                    }
                    key={connection.id}
                  >
                    <TableCell className="font-medium text-[var(--text-primary)]" width={160}>
                      {connection.connector}
                    </TableCell>
                    <TableCell width={180}>{connection.tenant}</TableCell>
                    <TableCell>{connection.scope}</TableCell>
                    <TableCell width={110}>
                      <StatusPill tone={STATUS[connection.status].tone}>
                        {STATUS[connection.status].label}
                      </StatusPill>
                    </TableCell>
                    <TableCell width={140}>{connection.lastSync}</TableCell>
                  </TableRow>
                ))}
              </>
            )}
          </CardBody>
        </Card>
      )}
      <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} title="Connection details">
        {selected && <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-3 text-sm">
          <dt className="text-[var(--text-tertiary)]">Connector</dt><dd>{selected.connector}</dd>
          <dt className="text-[var(--text-tertiary)]">Tenant</dt><dd>{selected.tenant}</dd>
          <dt className="text-[var(--text-tertiary)]">Scope</dt><dd>{selected.scope}</dd>
          <dt className="text-[var(--text-tertiary)]">Status</dt><dd><StatusPill tone={STATUS[selected.status].tone}>{STATUS[selected.status].label}</StatusPill></dd>
          <dt className="text-[var(--text-tertiary)]">Last sync</dt><dd>{selected.lastSync}</dd>
        </dl>}
      </Dialog>
    </>
  );
}
