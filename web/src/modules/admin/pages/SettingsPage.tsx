"use client";

import { useState } from "react";

import { SettingRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { Input } from "@/components/ui/Input";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { directoryApi, type Workspace } from "@/modules/admin/directory";
import { useAdminData } from "@/modules/admin/queries";

export function SettingsPage() {
  const session = useAuthSession();
  const tenantId = session?.active_tenant_id ?? null;
  const query = useAdminData(async () =>
    tenantId ? directoryApi.workspace(tenantId) : null,
  );
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  return query.data
    ? <WorkspaceSettings key={query.data.id} workspace={query.data} />
    : <p role="status">Loading settings…</p>;
}

function WorkspaceSettings({ workspace }: { workspace: Workspace }) {
  const [name, setName] = useState(workspace.name);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="configuration"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await directoryApi.saveWorkspace(workspace.id, { name });
          setNotice("Workspace settings saved");
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "Could not save the workspace.");
        } finally {
          setBusy(false);
        }
      }}
    >
      <section className="configuration-section">
        <h2>Workspace identity</h2>
        <label className="configuration-field">Name
          <Input onChange={(event) => setName(event.target.value)} required value={name} />
        </label>
        <label className="configuration-field">Code
          <Input readOnly value={workspace.code} />
          <span className="text-xs text-[var(--text-tertiary)]">Fixed at creation.</span>
        </label>
        <SettingRow
          control={<span className="text-sm capitalize">{workspace.status}</span>}
          description="Set by a platform administrator."
          title="Status"
        />
      </section>
      {error && <ErrorState description={error} layout="inline" />}
      <div className="unsaved-bar">
        <span role="status">{notice}</span>
        <Button disabled={!name.trim() || name === workspace.name} loading={busy} type="submit">
          Save changes
        </Button>
      </div>
    </form>
  );
}
