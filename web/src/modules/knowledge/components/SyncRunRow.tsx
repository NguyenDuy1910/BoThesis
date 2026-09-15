"use client";

import { Ban, Check, LoaderCircle, TriangleAlert, X } from "lucide-react";

import { cn } from "@/lib/cn";
import { relativeTime } from "@/modules/knowledge/connection-state";
import type { SourceRun } from "@/modules/knowledge/integrations-api";

/**
 * One sync run.
 *
 * A run is a line, not a card: what an operator scans for is whether anything
 * failed and when, and everything else is noise until one of them did. The
 * workflow id is shown only for a run that ended badly, because it is the one
 * thing worth quoting when asking someone to look it up.
 */
const MARK: Record<string, { Icon: typeof Check; tone: string; label: string }> = {
  running: { Icon: LoaderCircle, tone: "busy", label: "Syncing" },
  completed: { Icon: Check, tone: "ok", label: "Completed" },
  failed: { Icon: X, tone: "bad", label: "Failed" },
  cancelled: { Icon: Ban, tone: "warn", label: "Cancelled" },
  terminated: { Icon: Ban, tone: "bad", label: "Terminated" },
  timed_out: { Icon: TriangleAlert, tone: "bad", label: "Timed out" },
};

const UNKNOWN = { Icon: TriangleAlert, tone: "warn", label: "Unknown" } as const;

export function SyncRunRow({
  run,
  /** The workspace-wide feed names what was synced; an account's own list does not. */
  label,
}: {
  run: SourceRun;
  label?: string;
}) {
  const { Icon, tone, label: outcome } = MARK[run.status] ?? UNKNOWN;
  const failed = tone === "bad";

  return (
    <li className="knowledge-run">
      <div className="knowledge-run__summary knowledge-run__summary--static">
        <Icon
          aria-hidden="true"
          className={cn(
            `knowledge-run__mark knowledge-run__mark--${tone}`,
            run.status === "running" && "motion-safe:animate-spin",
          )}
          size={16}
        />
        <span className="knowledge-run__title">
          {label && <strong>{label}</strong>}
          {outcome}
          {run.trigger_type === "schedule" ? " · scheduled" : ""}
        </span>
        <time
          className="knowledge-run__time"
          dateTime={run.finished_at ?? run.started_at}
        >
          {relativeTime(run.finished_at ?? run.started_at)}
        </time>
      </div>
      {failed && (
        <details className="knowledge-run__technical">
          <summary>Technical details</summary>
          <code>{run.workflow_id}</code>
        </details>
      )}
    </li>
  );
}
