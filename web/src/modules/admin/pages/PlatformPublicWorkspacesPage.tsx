"use client";

import { Globe } from "lucide-react";
import { useMemo, useState } from "react";

import { SearchField, StatusPill, Toggle, WorkspaceRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { type PublicWorkspace } from "@/modules/admin/fixtures";
import { adminData, useAdminData } from "@/modules/admin/queries";

/**
 * Which tenants are open to everyone, and where a new person lands.
 *
 * Publishing is what makes a tenant discoverable without an invitation; the
 * landing tenant is where someone with no membership starts. Exactly one
 * tenant can be the landing, and it has to be a published one — selecting a
 * new landing publishes it rather than leaving an unreachable default.
 */
export function PlatformPublicWorkspacesPage() {
  const [query, setQuery] = useState("");
  const workspaces = useAdminData(adminData.platform.publicWorkspaces);
  const rows: PublicWorkspace[] = workspaces.data ?? [];

  const matching = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((row) => `${row.name} ${row.summary}`.toLowerCase().includes(term));
  }, [query, rows]);

  const published = matching.filter((row) => row.published);
  const unpublished = matching.filter((row) => !row.published);
  const landing = rows.find((row) => row.landing);

  const togglePublished = (id: string) =>
    void adminData.platform.savePublicWorkspaces(
      rows.map((row) =>
        row.id === id
          ? { ...row, published: !row.published, landing: row.landing && !row.published }
          : row,
      ));

  const makeLanding = (id: string) =>
    void adminData.platform.savePublicWorkspaces(
      rows.map((row) =>
        row.id === id ? { ...row, landing: true, published: true } : { ...row, landing: false },
      ));

  return (
    <>
      <div className="mb-4 flex items-center gap-3"><SearchField className="max-w-sm" onChange={setQuery} placeholder="Search tenants…" value={query} /><span className="text-sm text-[var(--text-secondary)]">{landing ? `Landing tenant: ${landing.name}` : "No landing tenant set"}</span></div>

      <div className="grid gap-4">
        <Card>
          <CardHeader
            description="Discoverable without an invitation. Anyone signed in can open these."
            title={`Published (${published.length})`}
          />
          <CardBody className="grid gap-1">
            {published.length === 0 ? (
              <EmptyState
                description="No tenant is published. New people have nowhere to land."
                icon={<Globe className="h-5 w-5" />}
                title="Nothing is public"
              />
            ) : (
              published.map((row) => (
                <WorkspaceRow
                  actions={
                    <div className="flex items-center gap-2">
                      {row.landing ? (
                        <StatusPill tone="accent">Landing</StatusPill>
                      ) : (
                        <Button onClick={() => makeLanding(row.id)} size="sm" variant="ghost">
                          Make landing
                        </Button>
                      )}
                      <Toggle
                        checked
                        label={`Unpublish ${row.name}`}
                        onChange={() => togglePublished(row.id)}
                      />
                    </div>
                  }
                  key={row.id}
                  name={row.name}
                  sublabel={`${row.summary} · ${row.members.toLocaleString()} members`}
                />
              ))
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            description="Reachable only by the people who hold a membership."
            title={`Private (${unpublished.length})`}
          />
          <CardBody className="grid gap-1">
            {unpublished.length === 0 ? (
              <EmptyState
                description="Every tenant on this deployment is public."
                icon={<Globe className="h-5 w-5" />}
                title="Nothing is private"
              />
            ) : (
              unpublished.map((row) => (
                <WorkspaceRow
                  actions={
                    <Toggle
                      checked={false}
                      label={`Publish ${row.name}`}
                      onChange={() => togglePublished(row.id)}
                    />
                  }
                  key={row.id}
                  name={row.name}
                  sublabel={`${row.summary} · ${row.members.toLocaleString()} members`}
                  tone="neutral"
                />
              ))
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
