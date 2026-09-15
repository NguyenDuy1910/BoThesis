"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { WorkspaceMark } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { directoryApi } from "@/modules/admin/directory";
import { useAdminData } from "@/modules/admin/queries";
import { describeAuditAction, formatRelative } from "@/modules/admin/format";

const METRICS: { key: string; label: string }[] = [
  { key: "active_users", label: "Members" },
  { key: "active_groups", label: "Groups" },
  { key: "active_roles", label: "Roles" },
  { key: "items", label: "Knowledge items" },
  { key: "active_integration_connections", label: "Connections" },
];

const ATTENTION: { key: string; label: string; href: string }[] = [
  { key: "pending_approval_requests", label: "Pending access requests", href: "/admin/access" },
  { key: "failed_items", label: "Failed documents", href: "/admin/knowledge" },
];

export function WorkspaceOverviewPage() {
  const query = useAdminData(directoryApi.overview);
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  if (!query.data) return <p role="status">Loading workspace…</p>;
  const { tenant, metrics, attention, recent_activity } = query.data;

  return (
    <div className="configuration">
      <div className="flex items-start gap-4 py-6">
        <WorkspaceMark name={tenant.name} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">{tenant.name}</h1>
          <p className="my-2 text-sm text-[var(--text-secondary)]">Workspace code {tenant.code}</p>
        </div>
        <Link href="/app">
          <Button variant="ghost">Open workspace <ArrowRight size={16} /></Button>
        </Link>
      </div>

      <StatGrid>
        {METRICS.map((metric) => (
          <StatTile key={metric.key} label={metric.label} value={String(metrics[metric.key] ?? 0)} />
        ))}
      </StatGrid>

      <div className="mt-4 grid gap-x-10 md:grid-cols-2">
        <section className="configuration-section">
          <SectionHeading action="Review" href="/admin/access">Needs attention</SectionHeading>
          {ATTENTION.map((item) => (
            <Link className="flex items-center justify-between gap-2 py-3 text-sm" href={item.href} key={item.key}>
              <span>{item.label}</span>
              <span className={attention[item.key] ? "text-[var(--status-danger-text)]" : "text-[var(--text-tertiary)]"}>
                {attention[item.key] ?? 0}
              </span>
            </Link>
          ))}
        </section>
        <section className="configuration-section">
          <SectionHeading action="View all" href="/admin/activity">Recent activity</SectionHeading>
          {recent_activity.length ? recent_activity.slice(0, 5).map((event) => (
            <div className="py-3 text-sm" key={event.id}>
              <p>{describeAuditAction(event.action)}</p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {event.actor.display_name ?? event.actor.email ?? "System"} · {formatRelative(event.created_at)}
              </p>
            </div>
          )) : (
            <p className="py-3 text-sm text-[var(--text-tertiary)]">Nothing recorded yet.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function SectionHeading({ children, href, action }: { children: React.ReactNode; href: string; action: string }) {
  return (
    <div className="mb-4 flex justify-between">
      <h2 className="!mb-0">{children}</h2>
      <Link className="text-sm text-[var(--text-accent)]" href={href}>{action}</Link>
    </div>
  );
}
