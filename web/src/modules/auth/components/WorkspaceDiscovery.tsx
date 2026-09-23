"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { DirectoryRow } from "@/components/patterns";
import { CommandBar } from "@/components/layout/CommandBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useWorkspaces, useWorkspaceSwitch } from "@/modules/auth/queries";
import { WorkspaceDiscoveryLoadingSkeleton } from "./WorkspaceDiscoveryLoadingSkeleton";

/**
 * The workspaces this person can open.
 *
 * Only memberships appear: the API issues a session for the workspaces someone
 * actually belongs to, and there is no notion of a workspace being listed to
 * people outside it. Showing a workspace nobody could then enter would be an
 * invitation the server refuses.
 */
export function WorkspaceDiscovery() {
  const router = useRouter();
  const query = useWorkspaces();
  const [search, setSearch] = useState("");
  const { error: switchError, switchingId, switchWorkspace } = useWorkspaceSwitch();
  const term = search.trim().toLowerCase();
  const rows = (query.data ?? []).filter(
    (item) => !term || `${item.name} ${item.code}`.toLowerCase().includes(term),
  );

  const openWorkspace = async (workspaceId: string) => {
    if (await switchWorkspace(workspaceId)) {
      router.replace("/app?action=new");
    }
  };

  if (query.loading) return <WorkspaceDiscoveryLoadingSkeleton />;

  if (query.error) {
    return (
      <section aria-label="Your workspaces" className="mx-auto w-full max-w-6xl p-[var(--page-gutter)]">
        <h1 className="mb-5 text-[length:var(--text-size-h2)] font-semibold">Your workspaces</h1>
        <ErrorState
          actionLabel="Retry"
          description={query.error}
          onAction={query.reload}
          title="Workspaces could not be loaded"
        />
      </section>
    );
  }

  return (
    <section aria-label="Your workspaces" className="mx-auto w-full max-w-6xl p-[var(--page-gutter)]">
      <h1 className="mb-5 text-[length:var(--text-size-h2)] font-semibold">Your workspaces</h1>
      <CommandBar
        count={`${rows.length} workspaces`}
        search={{
          value: search,
          onChange: setSearch,
          placeholder: "Search workspaces…",
          label: "Search workspaces",
        }}
      />
      {switchError && <ErrorState className="mt-3" description={switchError} layout="inline" />}
      {!rows.length ? (
        <EmptyState
          description="You belong to no workspace yet. An administrator can add you to one."
          title="No workspaces"
        />
      ) : (
        <div className="divide-y divide-[var(--border-subtle)]">
          {rows.map((item) => (
            <DirectoryRow
              description={item.role_codes.join(", ") || "Member"}
              disabled={Boolean(switchingId)}
              key={item.id}
              loading={switchingId === item.id}
              onOpen={() => void openWorkspace(item.id)}
              provider={`Workspace code ${item.code}`}
              title={item.name}
            />
          ))}
        </div>
      )}
    </section>
  );
}
