"use client";

import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  FileText,
  Plug,
  RotateCw,
  Upload,
  Users,
} from "lucide-react";
import Link from "next/link";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatsSkeleton, TableSkeleton } from "@/components/ui/Skeleton";
import { StatTile, StatGrid } from "@/components/ui/StatTile";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAdminQuery } from "@/modules/admin/api";
import { describeAuditAction, formatRelative, pluralize } from "@/modules/admin/format";
import { useAdminWorkspace, viewerName } from "@/modules/admin/workspace";

interface CountResult {
  total: number;
}

interface ActivityRow {
  id: string;
  action?: string;
  resource_type?: string;
  outcome?: string;
  created_at?: string;
  actor?: { display_name?: string | null; email?: string | null } | null;
}

/** Each attention counter, with the page that resolves it. */
const attentionRoutes: Record<string, { label: string; href: string; fix: string }> = {
  pending_approval_requests: {
    label: "access request",
    href: "/admin/access?tab=requests",
    fix: "Review requests",
  },
  failed_items: {
    label: "document failed to index",
    href: "/knowledge",
    fix: "Open Knowledge",
  },
};

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function DashboardPage() {
  const { overview, viewer, tenant, loading, error, reload } = useAdminWorkspace();
  const collections = useAdminQuery<CountResult>(
    "/items?item_type=collection&page_size=1",
  );
  const documents = useAdminQuery<CountResult>("/items?item_type=document&page_size=1");
  const failed = useAdminQuery<CountResult>(
    "/items?item_type=document&status=failed&page_size=1",
  );

  if (error) {
    return (
      <ErrorState
        actionLabel="Try again"
        description={error}
        onAction={reload}
        title="This workspace could not be loaded"
      />
    );
  }

  const metrics = overview?.metrics ?? {};
  const activity = (overview?.recent_activity ?? []) as unknown as ActivityRow[];
  const attention = Object.entries(overview?.attention ?? {})
    .map(([key, value]) => ({
      key,
      count: typeof value === "number" ? value : 0,
      ...(attentionRoutes[key] ?? {
        label: key.replace(/_/g, " "),
        href: "/admin/activity",
        fix: "Open",
      }),
    }))
    .filter((entry) => entry.count > 0);

  const connections =
    metrics.active_integration_connections ?? metrics.active_datasources;
  const firstName = viewerName(viewer).split(/[\s@]/)[0];
  const hasContent = (collections.data?.total ?? 0) > 0;

  return (
    <>
      <PageHeader
        actions={
          <>
            <Button
              icon={<RotateCw aria-hidden="true" className="h-4 w-4" />}
              onClick={() => {
                reload();
                collections.reload();
                documents.reload();
                failed.reload();
              }}
              variant="ghost"
            >
              Refresh
            </Button>
            <Link
              className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent-primary)] px-3 text-[0.8125rem] font-medium leading-none text-[var(--text-on-accent)] shadow-[var(--elevation-1)] transition-[background-color,color,box-shadow,opacity] duration-[var(--duration-fast)] ease-[var(--ease-out)] hover:bg-[var(--accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-canvas)]"
              href="/knowledge"
            >
              <Boxes aria-hidden="true" className="h-4 w-4" />
              Create collection
            </Link>
          </>
        }
        description={
          tenant ? `Here is what is happening in ${tenant.name}.` : undefined
        }
        title={loading ? "Dashboard" : `${greeting()}, ${firstName}`}
      />

      {/* Anything that needs a decision comes before anything that is merely
          informative, so the page opens with work rather than with numbers. */}
      {!loading &&
        (attention.length > 0 ? (
          <div className="mb-4 grid gap-2">
            {attention.map((entry) => (
              <Link
                className="group flex items-center gap-3 rounded-[var(--radius-md)] bg-[var(--status-warning-bg)] px-3.5 py-3 shadow-[inset_0_0_0_1px_var(--status-warning-border)] transition-colors hover:bg-[var(--status-warning-bg)]/80"
                href={entry.href}
                key={entry.key}
              >
                <Badge tone="warning">{entry.count}</Badge>
                <span className="min-w-0 flex-1 text-[0.8125rem] font-medium text-[var(--status-warning-text)]">
                  {pluralize(entry.count, entry.label)} need
                  {entry.count === 1 ? "s" : ""} your attention
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[0.8125rem] font-semibold text-[var(--status-warning-text)]">
                  {entry.fix}
                  <ArrowRight
                    aria-hidden="true"
                    className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
                  />
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="mb-4 flex items-center gap-2.5 rounded-[var(--radius-md)] bg-[var(--status-success-bg)] px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--status-success-border)]">
            <CheckCircle2
              aria-hidden="true"
              className="h-4 w-4 shrink-0 text-[var(--status-success-solid)]"
            />
            <p className="text-[0.8125rem] font-medium text-[var(--status-success-text)]">
              Nothing needs attention — every document is indexed and no access
              requests are waiting.
            </p>
          </div>
        ))}

      {loading ? (
        <StatsSkeleton />
      ) : (
        <StatGrid>
          <StatTile
            href="/knowledge"
            icon={<Boxes aria-hidden="true" className="h-3.5 w-3.5" />}
            label="Knowledge"
            note="Open the shared knowledge workspace"
            value={collections.data?.total}
          />
          <StatTile
            href="/knowledge"
            icon={<FileText aria-hidden="true" className="h-3.5 w-3.5" />}
            label="Documents"
            note={
              failed.data?.total
                ? `${failed.data.total} failed to index`
                : "All indexed and searchable"
            }
            tone={failed.data?.total ? "danger" : "default"}
            value={documents.data?.total}
          />
          <StatTile
            href="/admin/connectors"
            icon={<Plug aria-hidden="true" className="h-3.5 w-3.5" />}
            label="Connected sources"
            note={connections ? "Syncing into collections" : "None connected yet"}
            value={connections}
          />
          <StatTile
            href="/admin/access"
            icon={<Users aria-hidden="true" className="h-3.5 w-3.5" />}
            label="People"
            note={
              metrics.active_groups
                ? `${pluralize(metrics.active_groups, "group")}`
                : "No groups yet"
            }
            value={metrics.active_users}
          />
        </StatGrid>
      )}

      <div className="mt-4 grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader
            actions={
              <Link
                className="group inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2 py-1 text-[0.8125rem] font-medium text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
                href="/admin/audit"
              >
                Full audit log
                <ArrowRight
                  aria-hidden="true"
                  className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
                />
              </Link>
            }
            description="Every administrative change, newest first."
            title="Recent activity"
          />
          {loading ? (
            <TableSkeleton columns={3} rows={5} />
          ) : activity.length === 0 ? (
            <EmptyState
              description="Uploads, access changes and source syncs will appear here as they happen."
              icon={<FileText className="h-5 w-5" />}
              title="No activity yet"
            />
          ) : (
            <ul className="divide-y divide-[var(--border-subtle)]">
              {activity.slice(0, 8).map((row) => {
                const actor =
                  row.actor?.display_name || row.actor?.email || "System";
                return (
                  <li
                    className="flex items-center gap-3 px-4 py-2.5 text-[0.8125rem]"
                    key={row.id}
                  >
                    <Avatar name={actor} size="sm" />
                    <span className="min-w-0 flex-1 truncate text-[var(--text-secondary)]">
                      <span className="font-medium text-[var(--text-primary)]">{actor}</span>{" "}
                      {describeAuditAction(row.action).toLowerCase()}
                    </span>
                    {row.outcome && row.outcome !== "success" && (
                      <StatusBadge status={row.outcome} />
                    )}
                    <time
                      className="shrink-0 text-[0.75rem] tabular-nums text-[var(--text-tertiary)]"
                      dateTime={row.created_at}
                    >
                      {formatRelative(row.created_at)}
                    </time>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            description={
              hasContent
                ? "Common next steps in this workspace."
                : "Three steps to a workspace your team can ask questions of."
            }
            title={hasContent ? "Quick actions" : "Get started"}
          />
          <ol className="divide-y divide-[var(--border-subtle)]">
            <QuickAction
              description="Group related material so answers stay on topic."
              done={hasContent}
              icon={<Boxes aria-hidden="true" className="h-4 w-4" />}
              label="Create a collection"
              href="/knowledge"
            />
            <QuickAction
              description="Add PDFs, Word files and text straight from your machine."
              done={(documents.data?.total ?? 0) > 0}
              href="/knowledge"
              icon={<Upload aria-hidden="true" className="h-4 w-4" />}
              label="Upload documents"
            />
            <QuickAction
              description="Keep Confluence, Drive, Slack and more in sync automatically."
              done={Boolean(connections)}
              href="/admin/connectors"
              icon={<Plug aria-hidden="true" className="h-4 w-4" />}
              label="Connect a source"
            />
          </ol>
        </Card>
      </div>
    </>
  );
}

function QuickAction({
  description,
  done,
  href,
  icon,
  label,
  onClick,
}: {
  description: string;
  done: boolean;
  href?: string;
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span
        aria-hidden="true"
        className={
          done
            ? "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--status-success-bg)] text-[var(--status-success-solid)]"
            : "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent-soft)] text-[var(--text-accent)]"
        }
      >
        {done ? <CheckCircle2 className="h-4 w-4" /> : icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8125rem] font-medium text-[var(--text-primary)]">
          {label}
        </span>
        <span className="mt-0.5 block text-[0.75rem] leading-4 text-[var(--text-tertiary)]">
          {description}
        </span>
      </span>
      <ArrowRight
        aria-hidden="true"
        className="mt-1 h-3.5 w-3.5 shrink-0 text-[var(--text-tertiary)] transition-transform group-hover:translate-x-0.5"
      />
    </>
  );

  const className =
    "group flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--surface-hover)]";

  return (
    <li>
      {href ? (
        <Link className={className} href={href}>
          {body}
        </Link>
      ) : (
        <button className={className} onClick={onClick} type="button">
          {body}
        </button>
      )}
    </li>
  );
}
