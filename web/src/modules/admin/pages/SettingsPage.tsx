"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Select } from "@/components/ui/Select";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ErrorState } from "@/components/ui/ErrorState";
import { SettingRow } from "@/components/patterns";
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { Workspace } from "@/mocks/bothesis-api.mock";

export function SettingsPage() {
  const query = useAdminData(adminData.workspaces.get);
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  return query.data ? <WorkspaceSettings key={query.data.id} workspace={query.data} /> : <p role="status">Loading settings…</p>;
}
function WorkspaceSettings({ workspace }: { workspace: Workspace }) {
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description);
  const [retention, setRetention] = useState("24");
  const [archive, setArchive] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  return <form className="configuration" onSubmit={async (event) => { event.preventDefault(); setBusy(true); await adminData.workspaces.save(workspace.id, { name, description }); setNotice("Workspace settings saved"); setBusy(false); }}>
    <section className="configuration-section"><h2>Workspace identity</h2><label className="configuration-field">Name<Input required value={name} onChange={(event) => setName(event.target.value)} /></label><label className="configuration-field">Code<Input readOnly value={workspace.id} /><span className="text-xs text-[var(--text-tertiary)]">Fixed at creation.</span></label><label className="configuration-field">Description<Textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} /></label></section>
    <section className="configuration-section"><h2>Advanced</h2><SettingRow title="Data region" description="Cannot be changed after creation." control={<span className="text-sm">Singapore</span>} /><label className="configuration-field">Conversation retention<Select value={retention} onChange={(event) => setRetention(event.target.value)} options={[{ value: "12", label: "12 months" }, { value: "24", label: "24 months" }, { value: "36", label: "36 months" }]} /></label></section>
    <section className="configuration-section"><h2>Danger zone</h2><SettingRow title={workspace.status === "suspended" ? "Restore workspace" : "Archive workspace"} description="People lose access. Knowledge and conversations are retained and can be restored." control={<Button variant="danger" onClick={() => setArchive(true)}>{workspace.status === "suspended" ? "Restore" : "Archive"}</Button>} /></section>
    <div className="unsaved-bar"><span role="status">{notice}</span><Button type="submit" loading={busy} disabled={!name.trim()}>Save changes</Button></div>
    <ConfirmDialog open={archive} onClose={() => setArchive(false)} title={workspace.status === "suspended" ? "Restore workspace?" : "Archive workspace?"} description="Workspace access changes immediately. Existing knowledge and conversations are retained." confirmLabel={workspace.status === "suspended" ? "Restore" : "Archive"} onConfirm={async () => { await adminData.workspaces.save(workspace.id, { status: workspace.status === "suspended" ? "active" : "suspended" }); setArchive(false); setNotice("Workspace status updated"); }} />
  </form>;
}
