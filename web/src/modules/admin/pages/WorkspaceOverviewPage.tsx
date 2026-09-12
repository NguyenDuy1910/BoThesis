"use client";

import { ArrowRight, Bot, BookOpenCheck, CheckCircle2, Link2, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatGrid, StatTile } from "@/components/ui/StatTile";
import { useAdminQuery } from "@/modules/admin/api";
import { describeAuditAction, formatRelative } from "@/modules/admin/format";
import { useAdminWorkspace } from "@/modules/admin/workspace";
import { getAuthSession, hasPlatformScope } from "@/lib/auth/session";

interface CountResult { total: number }
interface Member { membership?: { role?: { code?: string; display_name?: string } }; status?: boolean }
interface Members { items: Member[]; total: number }
interface Activity { id: string; action?: string; created_at?: string; actor?: { display_name?: string | null; email?: string | null } | null }

export function WorkspaceOverviewPage() {
  const { overview, tenant, viewer, loading, error, reload } = useAdminWorkspace();
  const members = useAdminQuery<Members>("/users?page_size=100");
  const collections = useAdminQuery<CountResult>("/items?item_type=collection&page_size=1");
  const connections = useAdminQuery<CountResult>("/integration-connections?page_size=1");

  if (error) return <ErrorState actionLabel="Try again" description={error} onAction={reload} title="Workspace overview could not be loaded" />;

  const rows = members.data?.items ?? [];
  const roleCount = (role: string) => rows.filter((member) => member.membership?.role?.code === role && member.status).length;
  const metrics = overview?.metrics ?? {};
  const activity = (overview?.recent_activity ?? []) as unknown as Activity[];
  const role = viewer?.membership?.role?.display_name ?? "Workspace member";
  const rootScopeActive = hasPlatformScope(getAuthSession(), "root_admin");

  return (
    <>
      <PageHeader
        eyebrow={tenant?.name?.toUpperCase() ?? "MY WORKSPACE"}
        metadata={<Badge tone="brand">{role}</Badge>}
        description="Manage people, knowledge, apps, and agent policies inside the workspace you belong to."
        title="Workspace overview"
      />

      {rootScopeActive && (
        <p className="mb-4 rounded-[var(--radius-md)] bg-[var(--status-info-bg)] px-3.5 py-3 text-[0.8125rem] text-[var(--status-info-text)]">
          You are viewing this workspace with platform root scope. Your actor identity remains unchanged.
        </p>
      )}

      <StatGrid>
        <StatTile href="/admin/members" icon={<Users aria-hidden="true" className="h-3.5 w-3.5" />} label="Members" note={members.loading ? "Loading access…" : `${roleCount("owner")} owner · ${roleCount("admin")} admins`} value={loading ? undefined : members.data?.total ?? metrics.active_users} />
        <StatTile href="/admin/knowledge-governance" icon={<BookOpenCheck aria-hidden="true" className="h-3.5 w-3.5" />} label="Collections" note="Governed knowledge" value={collections.loading ? undefined : collections.data?.total} />
        <StatTile href="/admin/apps-permissions" icon={<Link2 aria-hidden="true" className="h-3.5 w-3.5" />} label="Connected apps" note="Workspace connections" value={connections.loading ? undefined : connections.data?.total ?? metrics.active_integration_connections} />
        <StatTile href="/admin/agents-policies" icon={<Bot aria-hidden="true" className="h-3.5 w-3.5" />} label="Agents" note="Agent policy management" value={undefined} />
      </StatGrid>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader description="This tenant is your workspace. Workspace administration is not platform administration." title="Workspace identity" />
          <CardBody>
            <dl className="grid gap-4 sm:grid-cols-2">
              <div><dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">Workspace</dt><dd className="mt-1 text-[0.8125rem] font-semibold text-[var(--text-primary)]">{tenant?.name ?? "—"}</dd></div>
              <div><dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">Your role</dt><dd className="mt-1"><Badge tone="success">{role}</Badge></dd></div>
            </dl>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Workspace setup" />
          <CardBody>
            <ol className="grid gap-3">
              <SetupStep detail="Invite your team and assign workspace roles." number="1" title="Members & roles" />
              <SetupStep detail="Control which collections members can retrieve." number="2" title="Knowledge access" />
              <SetupStep detail="Connect apps and govern external actions." number="3" title="Apps & actions" />
            </ol>
          </CardBody>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader actions={<Link className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-[var(--text-accent)]" href="/admin/audit">View audit <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" /></Link>} title="Recent workspace activity" />
          <CardBody>
            {activity.length ? <ul className="divide-y divide-[var(--border-subtle)]">{activity.slice(0, 4).map((entry) => <li className="flex items-center gap-3 py-3 text-[0.8125rem]" key={entry.id}><CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-[var(--text-accent)]" /><span className="min-w-0 flex-1 text-[var(--text-secondary)]"><strong className="font-semibold text-[var(--text-primary)]">{describeAuditAction(entry.action)}</strong>{entry.actor?.display_name ? ` · ${entry.actor.display_name}` : ""}</span><time className="shrink-0 text-[0.75rem] text-[var(--text-tertiary)]">{formatRelative(entry.created_at)}</time></li>)}</ul> : <EmptyState description="Member changes, permission updates, connections, and policy changes will appear here." icon={<ShieldCheck className="h-5 w-5" />} title="No workspace activity yet" />}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Permission model" />
          <CardBody>
            <Badge tone="brand">Workspace-scoped</Badge>
            <p className="mt-3 text-[0.8125rem] leading-5 text-[var(--text-secondary)]">Workspace roles grant administration only inside this workspace. Platform root access is a separate scope and is never implied by workspace ownership.</p>
            <dl className="mt-4 grid gap-2 text-[0.75rem]"><Permission role="Owner" detail="Full workspace administration" /><Permission role="Admin" detail="Delegated workspace management" /><Permission role="Member" detail="Granted knowledge and actions only" /></dl>
          </CardBody>
        </Card>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Link href="/admin/members"><Button>Invite members</Button></Link>
        <Link href="/admin/settings"><Button variant="secondary">Workspace settings</Button></Link>
      </div>
    </>
  );
}

function SetupStep({ detail, number, title }: { detail: string; number: string; title: string }) {
  return <li className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-2"><span className="grid h-5 w-5 place-items-center rounded-full bg-[var(--surface-selected)] text-[0.6875rem] font-semibold text-[var(--text-accent)]">{number}</span><span><strong className="text-[0.8125rem] text-[var(--text-primary)]">{title}</strong><span className="ml-2 text-[0.75rem] text-[var(--text-secondary)]">{detail}</span></span></li>;
}

function Permission({ detail, role }: { detail: string; role: string }) {
  return <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2"><dt className="font-semibold text-[var(--text-primary)]">{role}</dt><dd className="m-0 text-[var(--text-secondary)]">{detail}</dd></div>;
}
