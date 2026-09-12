"use client";

import { Activity, CheckCircle2, CircleAlert } from "lucide-react";

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAdminQuery } from "@/modules/admin/api";

interface HealthService { name: string; status: string; required: boolean; latency_ms: number; error_category?: string | null }
interface HealthReport { status: string; checked_at: string; services: HealthService[] }

export function SystemHealthPage() {
  const health = useAdminQuery<HealthReport>("/platform/health");
  if (health.error) return <ErrorState actionLabel="Try again" description={health.error} onAction={health.reload} title="System health could not be loaded" />;
  return (
    <>
      <PageHeader eyebrow="PLATFORM ADMIN" description="A concise readiness view for services used by Enterprise Agent. Detailed traces remain in Observability." title="System health" />
      <Card>
        <CardHeader
          actions={health.data && <StatusBadge status={health.data.status} />}
          description={health.data ? `Checked ${new Date(health.data.checked_at).toLocaleString()}` : "Checking platform dependencies…"}
          title="Service readiness"
        />
        <CardBody>
          <ul className="divide-y divide-[var(--border-subtle)]">{(health.data?.services ?? []).map((service) => <li className="flex items-center gap-3 py-3" key={service.name}>{service.status === "healthy" ? <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[var(--status-success-solid)]" /> : <CircleAlert aria-hidden="true" className="h-4 w-4 text-[var(--status-warning-solid)]" />}<span className="min-w-0 flex-1 text-[0.8125rem] font-medium text-[var(--text-primary)]">{service.name.replace(/_/g, " ")}{service.required ? "" : " · optional"}</span><span className="text-[0.75rem] text-[var(--text-tertiary)]">{service.latency_ms} ms</span><StatusBadge status={service.status} /></li>)}</ul>
          {health.loading && <p className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)]"><Activity aria-hidden="true" className="h-4 w-4 animate-pulse" />Checking platform services…</p>}
        </CardBody>
      </Card>
    </>
  );
}
