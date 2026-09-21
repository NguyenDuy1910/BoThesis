"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import type { Connection, Source, SourceRun } from "@/modules/knowledge/integrations-api";

import { SyncRunRow } from "./SyncRunRow";

/** The API's outcome names, as the filter menu offers them. */
const OUTCOME: Record<string, readonly string[]> = {
  complete: ["completed"],
  partial: ["running"],
  failed: ["failed", "terminated", "timed_out"],
};

/**
 * Every sync across the workspace, newest first.
 *
 * It is a log, so it reads as one: no cards, no per-run chrome, and the same
 * row an account's own page uses — with the source named, because here that is
 * the one fact the row cannot assume.
 */
export function SyncActivityView({
  runs,
  sources,
  connections,
  search,
  status,
  sort,
}: {
  runs: SourceRun[];
  sources: Source[];
  connections: Connection[];
  search: string;
  /** Empty shows every outcome. */
  status: string;
  sort: string;
}) {
  const needle = search.trim().toLowerCase();
  const nameFor = (run: SourceRun) => {
    const source = sources.find((item) => item.id === run.source_id);
    if (source) {
      const account = connections.find(
        (item) => item.id === source.connection_id,
      );
      return [account?.display_name, source.display_name].filter(Boolean).join(" · ");
    }
    return connections.find((item) => item.id === run.connection_id)
      ?.display_name ?? "Removed source";
  };

  const matched = runs
    .filter((run) => !status || (OUTCOME[status] ?? [status]).includes(run.status))
    .filter((run) => `${nameFor(run)} ${run.status}`.toLowerCase().includes(needle));
  // The feed arrives newest first; oldest is that order reversed.
  const filtered = sort === "oldest" ? [...matched].reverse() : matched;

  if (!filtered.length) {
    return (
      <div className="knowledge-activity">
        <EmptyState
          description={
            search || status
              ? "No run matches the current search and filters."
              : "Sync a connected account to see its activity here."
          }
          title={search || status ? "No matching activity" : "No sync activity"}
        />
      </div>
    );
  }

  return (
    <section aria-label="Sync activity" className="knowledge-activity">
      <ul className="knowledge-run-list">
        {filtered.map((run) => (
        <SyncRunRow key={`${run.id}:${run.id}`} label={nameFor(run)} run={run} />
        ))}
      </ul>
    </section>
  );
}
