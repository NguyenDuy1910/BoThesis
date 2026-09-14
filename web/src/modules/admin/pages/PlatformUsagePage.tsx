"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";

import { TableCell, TableHeader, TableRow, type TableColumn } from "@/components/patterns";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { usagePeriods } from "@/modules/admin/fixtures";
import { adminData, useAdminData } from "@/modules/admin/queries";

const COLUMNS: readonly TableColumn[] = [
  { id: "tenant", label: "Tenant" },
  { id: "conversations", label: "Conversations", width: 130 },
  { id: "messages", label: "Messages", width: 110 },
  { id: "documents", label: "Documents", width: 110 },
  { id: "tokens", label: "Tokens", width: 110 },
  { id: "cost", label: "Cost", width: 110 },
];

function compactNumber(value: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function money(value: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

/**
 * Volume and cost, per tenant.
 *
 * Cost is reported against the tenant that caused it, because the question
 * this page answers is always "which tenant, and is that expected" — never a
 * single deployment-wide number with no owner.
 */
export function PlatformUsagePage() {
  const [period, setPeriod] = useState("30d");
  const usage = useAdminData(adminData.platform.usage);
  const rows = useMemo(() => [...(usage.data ?? [])].sort((a, b) => b.cost - a.cost), [usage.data]);

  const totals = rows.reduce(
    (sum, row) => ({
      conversations: sum.conversations + row.conversations,
      messages: sum.messages + row.messages,
      tokens: sum.tokens + row.tokens,
      cost: sum.cost + row.cost,
    }),
    { conversations: 0, messages: 0, tokens: 0, cost: 0 },
  );

  return (
    <>
      <div className="mb-4 flex justify-end">
          <Select
            aria-label="Reporting period"
            className="w-44"
            onChange={(event) => setPeriod(event.target.value)}
            options={usagePeriods}
            value={period}
          />
      </div>

      <StatGrid>
        <StatTile label="Conversations" note={`${rows.length} tenants`} value={compactNumber(totals.conversations)} />
        <StatTile label="Messages" note="Across every tenant" value={compactNumber(totals.messages)} />
        <StatTile label="Tokens" note="Input and output" value={compactNumber(totals.tokens)} />
        <StatTile label="Cost" note="Billed to the deployment" value={money(totals.cost)} />
      </StatGrid>

      <Card className="mt-4">
        <CardHeader description="Ordered by cost. The change is against the previous period of the same length." title="By tenant" />
        <CardBody className="px-0 pb-0">
          <TableHeader columns={COLUMNS} />
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium text-[var(--text-primary)]">
                <span className="flex items-center gap-2">
                  {row.tenant}
                  {row.trend !== 0 && (
                    <span
                      className={
                        row.trend > 0
                          ? "inline-flex items-center gap-0.5 text-[length:var(--text-size-caption)] text-[var(--status-warning-text)]"
                          : "inline-flex items-center gap-0.5 text-[length:var(--text-size-caption)] text-[var(--status-success-text)]"
                      }
                    >
                      {row.trend > 0 ? (
                        <TrendingUp aria-hidden="true" size={13} />
                      ) : (
                        <TrendingDown aria-hidden="true" size={13} />
                      )}
                      {Math.abs(row.trend)}%
                    </span>
                  )}
                </span>
              </TableCell>
              <TableCell width={130}>{row.conversations.toLocaleString()}</TableCell>
              <TableCell width={110}>{compactNumber(row.messages)}</TableCell>
              <TableCell width={110}>{row.documents.toLocaleString()}</TableCell>
              <TableCell width={110}>{compactNumber(row.tokens)}</TableCell>
              <TableCell className="text-[var(--text-primary)]" width={110}>{money(row.cost)}</TableCell>
            </TableRow>
          ))}
        </CardBody>
      </Card>
    </>
  );
}
