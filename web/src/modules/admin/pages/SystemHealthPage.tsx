"use client";

import { Activity, CheckCircle2, CircleAlert } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { directoryApi } from "@/modules/admin/directory";
import { useAdminData } from "@/modules/admin/queries";

export function SystemHealthPage() {
  const health = useAdminData(directoryApi.platform.health);
  if (health.error) {
    return <ErrorState description={health.error} onAction={health.reload} />;
  }
  if (!health.data) {
    return (
      <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <Activity className="h-4 w-4 animate-pulse" />Checking platform services…
      </p>
    );
  }
  const { services, status, checked_at, duration_ms } = health.data;
  const required = services.filter((service) => service.required);
  return (
    <>
      <StatGrid>
        <StatTile label="Overall status" note={checked_at} value={status} />
        <StatTile
          label="Required services"
          note={`${required.length} checked`}
          value={`${required.filter((service) => service.status === "healthy").length}/${required.length} healthy`}
        />
        <StatTile label="Check duration" note="Round trip for this probe" value={`${duration_ms} ms`} />
      </StatGrid>
      <Card className="mt-4">
        <CardHeader
          actions={<StatusBadge status={status} />}
          description="Operational state for services used by BoThesis. Detailed traces remain in observability."
          title="Service readiness"
        />
        <CardBody>
          <ul className="divide-y divide-[var(--border-subtle)]">
            {services.map((service) => (
              <li className="flex min-h-14 items-center gap-3 py-3" key={service.name}>
                {service.status === "healthy" ? (
                  <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[var(--status-success-solid)]" />
                ) : (
                  <CircleAlert aria-hidden="true" className="h-4 w-4 text-[var(--status-warning-solid)]" />
                )}
                <span className="min-w-0 flex-1 text-sm font-medium text-[var(--text-primary)]">
                  {service.name}{service.required ? "" : " · optional"}
                </span>
                {service.latency_ms != null && (
                  <span className="text-xs text-[var(--text-tertiary)]">{service.latency_ms} ms</span>
                )}
                <StatusBadge status={service.status} />
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </>
  );
}
