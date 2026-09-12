"use client";

import { ArrowLeft, Building2, CheckCircle2, Link2, ShieldCheck, UsersRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { getAuthSession } from "@/lib/auth/session";
import { switchWorkspace } from "@/modules/auth/api";
import { useAdminQuery } from "@/modules/admin/api";

interface PlatformWorkspaceHealth {
  id: string;
  name: string;
  status: string;
  member_count: number;
  connection_count: number;
}

interface PlatformOverview {
  metrics: {
    workspaces?: number;
    users?: number;
    connections?: number;
    open_reviews?: number;
  };
  workspace_health: PlatformWorkspaceHealth[];
}

export function PlatformOverviewPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useAdminQuery<PlatformOverview>("/platform/overview");
  const [returning, setReturning] = useState(false);
  const session = getAuthSession();
  const returnWorkspace = session?.tenants.find((tenant) => tenant.role_code === "owner") ?? session?.tenants[0];

  async function returnToWorkspace() {
    if (!returnWorkspace) return;
    setReturning(true);
    try {
      await switchWorkspace(returnWorkspace.id);
      router.replace("/admin");
      router.refresh();
    } finally {
      setReturning(false);
    }
  }

  if (error) {
    return <ErrorState actionLabel="Try again" description={error} onAction={reload} title="Platform overview could not be loaded" />;
  }

  return (
    <>
      <PageHeader
        eyebrow="PLATFORM ADMIN"
        metadata={<Badge tone="info">Root access</Badge>}
        description="Operate across workspaces with elevated scope while remaining the same user identity."
        title="Platform overview"
      />

      <Card className="mb-4 bg-[var(--status-info-bg)] shadow-[inset_0_0_0_1px_var(--status-info-border)]">
        <CardBody className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <p className="text-[0.8125rem] font-semibold text-[var(--status-info-text)]">You are operating with platform-wide scope</p>
            <p className="mt-0.5 text-[0.75rem] text-[var(--text-secondary)]">Root administration is an additional authorization scope on your user account — not a separate identity.</p>
          </div>
          {returnWorkspace && (
            <Button icon={<ArrowLeft aria-hidden="true" className="h-4 w-4" />} loading={returning} onClick={() => void returnToWorkspace()} size="sm" variant="secondary">
              Return to My Workspace
            </Button>
          )}
        </CardBody>
      </Card>

      <StatGrid>
        <StatTile href="/admin/platform/workspaces" icon={<Building2 aria-hidden="true" className="h-3.5 w-3.5" />} label="Workspaces" note="Across the platform" value={loading ? undefined : data?.metrics.workspaces} />
        <StatTile href="/admin/platform/users" icon={<UsersRound aria-hidden="true" className="h-3.5 w-3.5" />} label="Users" note="Active accounts" value={loading ? undefined : data?.metrics.users} />
        <StatTile icon={<Link2 aria-hidden="true" className="h-3.5 w-3.5" />} label="Connections" note="Durable app connections" value={loading ? undefined : data?.metrics.connections} />
        <StatTile icon={<ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />} label="Open reviews" note="Pending approval requests" tone={(data?.metrics.open_reviews ?? 0) > 0 ? "warning" : "default"} value={loading ? undefined : data?.metrics.open_reviews} />
      </StatGrid>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader description="Current lifecycle and connection facts by workspace." title="Workspace health" />
          <CardBody>
            <ul className="divide-y divide-[var(--border-subtle)]">
              {(data?.workspace_health ?? []).map((workspace) => (
                <li className="flex items-center gap-3 py-3 text-[0.8125rem]" key={workspace.id}>
                  <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-[var(--status-success-solid)]" />
                  <span className="min-w-0 flex-1 font-medium text-[var(--text-primary)]">{workspace.name}</span>
                  <span className="hidden text-[var(--text-tertiary)] sm:inline">{workspace.member_count} members</span>
                  <StatusBadge status={workspace.status} />
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
        <Card>
          <CardHeader description="Platform controls are separate from workspace settings." title="Platform controls" />
          <CardBody>
            <ul className="grid gap-4 text-[0.8125rem]">
              <li><p className="font-semibold text-[var(--text-primary)]">Workspace lifecycle</p><p className="mt-0.5 text-[var(--text-secondary)]">Review status and ownership from the workspace directory.</p></li>
              <li><p className="font-semibold text-[var(--text-primary)]">Global policies</p><p className="mt-0.5 text-[var(--text-secondary)]">Platform defaults are shown separately from workspace configuration.</p></li>
              <li><p className="font-semibold text-[var(--text-primary)]">Platform audit</p><p className="mt-0.5 text-[var(--text-secondary)]">Trace platform administrative activity with actor and workspace context.</p></li>
            </ul>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
