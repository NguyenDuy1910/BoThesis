"use client";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { WorkspaceMark } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { adminData, useAdminData } from "@/modules/admin/queries";

export function WorkspaceOverviewPage() {
  const query = useAdminData(async () => ({ workspace: await adminData.workspaces.get(), sources: await adminData.knowledge.sources(), agent: await adminData.agent.get(), experience: await adminData.experience.get(), activity: await adminData.activity.list() }));
  if (query.error) return <ErrorState description={query.error} onAction={query.reload} />;
  if (!query.data) return <p role="status">Loading workspace…</p>;
  const { workspace, sources, agent, experience, activity } = query.data;
  return <div className="configuration">
    <div className="flex items-start gap-4 py-6"><WorkspaceMark name={workspace.name} size="lg" /><div className="min-w-0 flex-1"><h1 className="text-xl font-semibold">{workspace.name}</h1><p className="my-2 text-sm text-[var(--text-secondary)]">{workspace.description}</p><div className="flex flex-wrap items-center gap-3"><Badge tone="neutral">{workspace.access === "everyone" ? "Available to everyone" : "Members only"}</Badge><span className="text-xs text-[var(--text-tertiary)]">{workspace.discoverable ? "Shown in workspace discovery" : "Unlisted"}</span></div></div><Link href="/app"><Button variant="ghost">Open workspace <ArrowRight size={16} /></Button></Link></div>
    <div className="grid gap-x-10 md:grid-cols-2">
      <section className="configuration-section"><SectionHeading href="/admin/knowledge" action="Manage">Knowledge</SectionHeading>{sources.map((source) => <Link href={"/admin/knowledge?tab=sources&source=" + source.id} className="flex items-center justify-between gap-2 py-3 text-sm" key={source.id}><span>{source.name}</span><span className={source.status === "failed" ? "text-[var(--status-danger-text)]" : "text-[var(--text-tertiary)]"}>{source.status === "failed" ? "Needs attention" : source.documents + " documents"}</span></Link>)}</section>
      <section className="configuration-section"><SectionHeading href="/admin/agent" action="Configure">Agent</SectionHeading><dl className="grid grid-cols-2 gap-4 text-sm"><dt>Default model</dt><dd>{agent.model === "gpt-5.6" ? "GPT-5.6" : agent.model}</dd><dt>Knowledge search</dt><dd>{agent.knowledgeOnly ? "Enabled" : "Disabled"}</dd><dt>Web search</dt><dd>{agent.web ? "Enabled" : "Disabled"}</dd><dt>Artifacts</dt><dd>{agent.artifacts ? "Enabled" : "Disabled"}</dd></dl></section>
      <section className="configuration-section"><SectionHeading href="/admin/experience" action="Customize">Experience</SectionHeading><p className="py-5 text-lg font-medium">{experience.welcomeHeadline}</p><p className="text-sm text-[var(--text-secondary)]">{experience.welcomeBody}</p><p className="mt-5 text-xs text-[var(--text-tertiary)]">{experience.starterPrompts.length} starter prompts · {experience.accent} accent</p></section>
      <section className="configuration-section"><SectionHeading href="/admin/activity" action="View all">Recent activity</SectionHeading>{activity.slice(0, 4).map((event) => <div className="py-3 text-sm" key={event.id}><p>{event.action}</p><p className="mt-1 text-xs text-[var(--text-tertiary)]">{event.actor} · {event.time}</p></div>)}</section>
    </div>
  </div>;
}
function SectionHeading({ children, href, action }: { children: React.ReactNode; href: string; action: string }) {
  return <div className="mb-4 flex justify-between"><h2 className="!mb-0">{children}</h2><Link className="text-sm text-[var(--text-accent)]" href={href}>{action}</Link></div>;
}
