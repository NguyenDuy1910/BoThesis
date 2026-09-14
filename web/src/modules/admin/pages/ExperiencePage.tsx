"use client";
import { Plus, X } from "lucide-react";
import { useRef, useState } from "react";
import { CapabilityChip, Composer, StarterPrompt, WorkspaceMark } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState } from "@/components/ui/ErrorState";
import { adminData, useAdminData } from "@/modules/admin/queries";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import type { WorkspaceExperience } from "@/mocks/bothesis-api.mock";

export function ExperiencePage() {
  const query = useAdminData(adminData.experience.get);
  const session = useAuthSession();
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  return query.data ? <ExperienceEditor key={session?.active_tenant_id} initial={query.data} /> : <p role="status">Loading experience…</p>;
}

function ExperienceEditor({ initial }: { initial: WorkspaceExperience }) {
  const [settings, setSettings] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [prompt, setPrompt] = useState("");
  const [compact, setCompact] = useState("desktop");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const upload = useRef<HTMLInputElement>(null);
  const update = <K extends keyof WorkspaceExperience>(key: K, value: WorkspaceExperience[K]) => setSettings((current) => ({ ...current, [key]: value }));
  const dirty = JSON.stringify(settings) !== JSON.stringify(saved);
  return <form onSubmit={async (event) => { event.preventDefault(); setBusy(true); await adminData.experience.save(settings); setSaved(structuredClone(settings)); setBusy(false); setNotice("Experience saved"); }}>
    <div className="experience-layout">
      <div>
        <section className="configuration-section"><h2>Brand</h2>
          <div className="mb-5 flex items-center gap-3">{settings.icon ? <img alt="Workspace icon" className="h-10 w-10 rounded-lg object-cover" src={settings.icon} /> : <WorkspaceMark name={settings.workspaceName} size="lg" />}<span className="flex-1 text-sm">Workspace icon</span><Button variant="ghost" onClick={() => upload.current?.click()}>Change</Button></div>
          <input accept="image/png,image/jpeg,image/svg+xml" type="file" className="hidden" aria-label="Workspace icon file" ref={upload} onChange={(event) => { const file = event.target.files?.[0]; if (!file || !file.type.startsWith("image/") || file.size > 2_000_000) { setNotice("Choose an image smaller than 2 MB."); return; } const reader = new FileReader(); reader.onload = () => update("icon", String(reader.result)); reader.readAsDataURL(file); }} />
          <label className="configuration-field">Display name<Input required maxLength={60} value={settings.workspaceName} onChange={(event) => update("workspaceName", event.target.value)} /></label>
        </section>
        <section className="configuration-section"><h2>Theme</h2>
          <label className="configuration-field">Accent<Select value={settings.accent} onChange={(event) => update("accent", event.target.value)} options={[{ value: "indigo", label: "Indigo" }, { value: "teal", label: "Teal" }, { value: "amber", label: "Amber" }, { value: "rose", label: "Rose" }]} /></label>
          <label className="configuration-field">Appearance<Select value={settings.appearance} onChange={(event) => update("appearance", event.target.value as WorkspaceExperience["appearance"])} options={[{ value: "system", label: "System" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} /></label>
          <label className="configuration-field">Background<Select value={settings.background} onChange={(event) => update("background", event.target.value as WorkspaceExperience["background"])} options={[{ value: "plain", label: "None" }, { value: "soft", label: "Subtle tint" }, { value: "gradient", label: "Soft gradient" }]} /></label>
        </section>
        <section className="configuration-section"><h2>Welcome</h2><label className="configuration-field">Heading<Input required maxLength={80} value={settings.welcomeHeadline} onChange={(event) => update("welcomeHeadline", event.target.value)} /></label><label className="configuration-field">Description<Textarea rows={3} maxLength={220} value={settings.welcomeBody} onChange={(event) => update("welcomeBody", event.target.value)} /></label></section>
        <section className="configuration-section"><h2>Starter prompts</h2>{settings.starterPrompts.map((item, index) => <div className="mb-2 flex gap-2" key={index}><Input aria-label={"Starter prompt " + (index + 1)} value={item} onChange={(event) => update("starterPrompts", settings.starterPrompts.map((text, i) => i === index ? event.target.value : text))} /><Button aria-label={"Remove starter prompt " + (index + 1)} icon={<X size={16} />} iconOnly variant="ghost" onClick={() => update("starterPrompts", settings.starterPrompts.filter((_, i) => i !== index))} /></div>)}
          {settings.starterPrompts.length < 4 && <div className="flex gap-2"><Input aria-label="New starter prompt" placeholder="Add prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} /><Button aria-label="Add starter prompt" icon={<Plus size={16} />} iconOnly variant="ghost" disabled={!prompt.trim()} onClick={() => { update("starterPrompts", [...settings.starterPrompts, prompt.trim()]); setPrompt(""); }} /></div>}
        </section>
      </div>
      <aside className="min-w-0"><div className="mb-4 flex items-center justify-between"><span className="text-sm font-medium">Live preview</span><Tabs density="compact" ariaLabel="Preview viewport" activeTab={compact} onChange={setCompact} tabs={[{ id: "desktop", label: "Desktop" }, { id: "compact", label: "Compact" }]} /></div>
        <div className="experience-preview mx-auto" data-accent={settings.accent} data-appearance={settings.appearance} data-background={settings.background} style={{ maxWidth: compact === "compact" ? 360 : undefined }}>
          <div className="mb-5 flex items-center justify-center gap-2">{settings.icon ? <img alt="" className="h-8 w-8 rounded-lg object-cover" src={settings.icon} /> : <WorkspaceMark name={settings.workspaceName} size="md" />}<span className="text-sm">{settings.workspaceName}</span></div>
          <h2 className="text-center text-[length:var(--text-size-h2)] font-semibold">{settings.welcomeHeadline}</h2><p className="my-5 text-center text-sm opacity-80">{settings.welcomeBody}</p>
          <div className="mb-5 flex flex-wrap justify-center gap-2">{settings.starterPrompts.map((item, index) => <StarterPrompt key={index} label={item} onSelect={() => setNotice("Preview prompt: " + item)} />)}</div>
          <Composer disabled value="" onChange={() => undefined} placeholder={"Ask " + settings.workspaceName + "…"} capabilities={<><CapabilityChip label="Knowledge: workspace" muted /><CapabilityChip label="Web: off" muted /></>} />
        </div>
      </aside>
    </div>
    <div className="unsaved-bar"><span role="status">{dirty ? "Unsaved changes" : notice || "Updates as you edit"}</span><Button variant="ghost" disabled={!dirty} onClick={() => setSettings(structuredClone(saved))}>Discard</Button><Button type="submit" disabled={!dirty || !settings.workspaceName.trim()} loading={busy}>Save changes</Button></div>
  </form>;
}
