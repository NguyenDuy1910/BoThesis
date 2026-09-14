"use client";

import { Activity, CheckCircle2, CircleAlert } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { adminData, useAdminData } from "@/modules/admin/queries";

export function SystemHealthPage() {
  const health = useAdminData(adminData.platform.system);
  if (health.error) return <ErrorState description={health.error} onAction={health.reload} />;
  if (!health.data) return <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]"><Activity className="h-4 w-4 animate-pulse" />Checking platform services…</p>;
  return <>
    <StatGrid>
      <StatTile label="Overall status" value="Healthy" note={health.data.checkedAt} />
      <StatTile label="Release" value={health.data.version} note="Frontend preview" />
      <StatTile label="Region" value={health.data.region} note="Primary deployment" />
    </StatGrid>
    <Card className="mt-4">
      <CardHeader title="Service readiness" description="Operational state for services used by BoThesis. Detailed traces remain in observability." actions={<StatusBadge status={health.data.status} />} />
      <CardBody><ul className="divide-y divide-[var(--border-subtle)]">{health.data.services.map((service) => <li className="flex min-h-14 items-center gap-3 py-3" key={service.id}>{service.status === "healthy" ? <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[var(--status-success-solid)]" /> : <CircleAlert aria-hidden="true" className="h-4 w-4 text-[var(--status-warning-solid)]" />}<span className="min-w-0 flex-1 text-sm font-medium text-[var(--text-primary)]">{service.name}{service.required ? "" : " · optional"}</span><span className="text-xs text-[var(--text-tertiary)]">{service.latency} ms</span><StatusBadge status={service.status} /></li>)}</ul></CardBody>
    </Card>
  </>;
}
