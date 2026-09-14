"use client";
import Link from "next/link";
import { useState } from "react";
import { SettingRow, Toggle, WorkspaceMark } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { ErrorState } from "@/components/ui/ErrorState";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { adminData, useAdminData } from "@/modules/admin/queries";
import type { AgentSettings } from "@/mocks/bothesis-api.mock";

export function AgentsPoliciesPage() {
  const query = useAdminData(adminData.agent.get);
  const session = useAuthSession();
  if (query.error) return <ErrorState title="Agent could not be loaded" description={query.error} onAction={query.reload} />;
  if (!query.data) return <p role="status">Loading agent…</p>;
  return <AgentEditor key={session?.active_tenant_id} initial={query.data} />;
}

function AgentEditor({ initial }: { initial: AgentSettings }) {
  const [settings, setSettings] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [notice, setNotice] = useState("");
  const dirty = JSON.stringify(settings) !== JSON.stringify(saved);
  const update = <K extends keyof AgentSettings>(key: K, value: AgentSettings[K]) => setSettings((current) => ({ ...current, [key]: value }));
  const toggle = (key: "knowledgeOnly" | "askClarification" | "web" | "analysis" | "artifacts" | "approval", label: string) => <Toggle label={label} checked={settings[key]} onChange={(value) => update(key, value)} />;
  return <form className="configuration" onSubmit={async (event) => { event.preventDefault(); setBusy(true); try { await adminData.agent.save(settings); setSaved(structuredClone(settings)); setNotice("Agent changes saved"); } finally { setBusy(false); } }}>
    <section className="configuration-section"><h2>Identity</h2><div className="mb-5 flex items-center gap-3"><WorkspaceMark name={settings.name} size="lg" /><span className="text-sm text-[var(--text-secondary)]">Workspace agent</span><Link className="ml-auto text-sm text-[var(--text-accent)]" href="/admin/experience">Change avatar</Link></div><label className="configuration-field">Display name<Input required maxLength={60} value={settings.name} onChange={(event) => update("name", event.target.value)} /></label><label className="configuration-field">Description<Input value={settings.description} onChange={(event) => update("description", event.target.value)} /></label></section>
    <section className="configuration-section"><h2>Instructions</h2><label className="configuration-field">System instructions<Textarea required rows={7} maxLength={4000} value={settings.instructions} onChange={(event) => update("instructions", event.target.value)} /></label><p className="text-xs text-[var(--text-tertiary)]">{settings.instructions.length} of 4,000 characters</p></section>
    <section className="configuration-section"><h2>Model</h2><label className="configuration-field">Default model<Select value={settings.model} onChange={(event) => update("model", event.target.value)} options={[{ value: "gpt-5.6", label: "GPT-5.6 · Platform default" }, { value: "sonnet", label: "Claude Sonnet" }, { value: "haiku", label: "Haiku 4.5" }]} /></label></section>
    <section className="configuration-section"><h2>Knowledge behaviour</h2>
      <SettingRow title="Search knowledge before answering" description="Search the workspace's permitted sources first." control={toggle("knowledgeOnly", "Search knowledge before answering")} />
      <SettingRow title="Always cite sources" description="Managed by BoThesis — cannot be turned off." control={<Toggle label="Always cite sources" checked disabled />} />
      <SettingRow title="Ask when information is missing" description="Ask a clarifying question when the evidence is incomplete." control={toggle("askClarification", "Ask when information is missing")} />
    </section>
    <section className="configuration-section"><h2>Capabilities</h2>
      <SettingRow title="Artifacts" description="Create documents, checklists and tables alongside answers." control={toggle("artifacts", "Artifacts")} />
      <SettingRow title="Web search" description="Use public sources beyond workspace knowledge." control={toggle("web", "Web search")} />
      <SettingRow title="File uploads in chat" description="Analyze files attached to a conversation." control={toggle("analysis", "File uploads in chat")} />
      <SettingRow title="Code execution" description="Not enabled for this deployment." control={<Toggle label="Code execution" checked={false} disabled />} />
    </section>
    <section className="configuration-section"><h2>Tools &amp; skills</h2>
      {["Search workspace knowledge", "Read document", "Create document", "Academic calendar lookup", "Student record lookup", "Send email"].map((tool) => <SettingRow key={tool} title={tool} description={tool === "Send email" ? "Requires approval before sending." : ""} control={<Toggle label={tool} checked={settings.tools.includes(tool)} onChange={(enabled) => update("tools", enabled ? [...settings.tools, tool] : settings.tools.filter((item) => item !== tool))} />} />)}
      <SettingRow title="Require approval for external actions" description="Ask before acting in another system." control={toggle("approval", "Require approval for external actions")} />
    </section>
    <section className="configuration-section"><Button variant="ghost" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>Advanced</Button>{advanced && <label className="configuration-field mt-4">Temperature · {settings.temperature}<input aria-label="Temperature" type="range" min="0" max="1" step="0.1" value={settings.temperature} onChange={(event) => update("temperature", Number(event.target.value))} /></label>}</section>
    <div className="unsaved-bar"><span role="status">{dirty ? "Unsaved changes" : notice || "All changes saved"}</span><Link href="/app?action=new"><Button variant="ghost">Test in workspace</Button></Link><Button variant="ghost" disabled={!dirty} onClick={() => setSettings(structuredClone(saved))}>Discard</Button><Button disabled={!dirty || !settings.name.trim() || !settings.instructions.trim()} loading={busy} type="submit">Save changes</Button></div>
  </form>;
}
