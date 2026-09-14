"use client";
import { ArrowLeft, Plug, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { knowledgeActions } from "@/modules/knowledge/queries";
import type { Source, SyncRun } from "@/mocks/bothesis-api.mock";

export function KnowledgeSources({ sources, runs, activity = false, search }: { sources: Source[]; runs: SyncRun[]; activity?: boolean; search: string }) {
  const [selectedId, setSelectedId] = useRouteState("source");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = sources.find((source) => source.id === selectedId);
  const sync = async (source: Source) => {
    setBusy(true); setError(null);
    try { await knowledgeActions.sync(source.id); } catch (cause) { setError(cause instanceof Error ? cause.message : "Sync failed."); } finally { setBusy(false); }
  };
  if (activity) return <DataTable ariaLabel="Sync activity" data={runs.filter((run) => run.source.toLowerCase().includes(search.toLowerCase()))} columns={[{ key: "source", label: "Source", sortable: true }, { key: "time", label: "Started" }, { key: "status", label: "Status", render: (run) => <Badge tone={run.status === "failed" ? "danger" : run.status === "running" ? "info" : "success"}>{run.status}</Badge> }, { key: "added", label: "Added", align: "right" }, { key: "updated", label: "Updated", align: "right" }]} emptyState={<EmptyState title="No sync runs" description="Sync a source to see its activity here." />} />;
  if (selected) return <section className="configuration">
    <Button icon={<ArrowLeft size={15} />} variant="ghost" onClick={() => setSelectedId("")}>Sources</Button>
    <div className="flex items-center gap-3 py-5"><Plug size={22} /><div className="flex-1"><h2 className="font-medium">{selected.name}</h2><p className="text-sm text-[var(--text-secondary)]">{selected.provider} · {selected.documents} documents</p></div><Badge tone={selected.status === "failed" ? "danger" : "success"}>{selected.status}</Badge><Button loading={busy || selected.status === "syncing"} onClick={() => sync(selected)}>Sync now</Button></div>
    {selected.status === "failed" && <ErrorState title="Source authorization expired" description="Reconnect this source to resume syncing. Existing documents retain their source permissions." actionLabel="Reconnect" onAction={() => sync(selected)} />}
    {error && <ErrorState title="Sync could not finish" description={error} onAction={() => sync(selected)} />}
    <section className="configuration-section"><h2>Connection</h2><dl className="grid grid-cols-[140px_1fr] gap-4 text-sm"><dt>Provider</dt><dd>{selected.provider}</dd><dt>Permission</dt><dd>Read-only · Source permissions remain authoritative</dd><dt>Scope</dt><dd>{selected.scope}</dd><dt>Schedule</dt><dd>Every hour</dd><dt>File types</dt><dd>PDF, DOCX, XLSX, TXT</dd><dt>Last sync</dt><dd>{selected.lastSync}</dd></dl><div className="mt-5 flex gap-2"><Button variant="ghost" onClick={() => sync(selected)}>Reconnect</Button><Button variant="ghost" onClick={() => knowledgeActions.pause(selected.id)}>Pause sync</Button></div></section>
    <section className="configuration-section"><h2>Sync history</h2>{runs.filter((run) => run.source === selected.name).map((run) => <p key={run.id} className="flex justify-between py-3 text-sm"><span>Sync {run.status} · {run.updated} documents updated</span><span className="text-[var(--text-tertiary)]">{run.time}</span></p>)}{!runs.some((run) => run.source === selected.name) && <p className="text-sm text-[var(--text-tertiary)]">No recent runs. Sync this source to refresh its content.</p>}</section>
  </section>;
  const filtered = sources.filter((source) => `${source.name} ${source.provider}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="divide-y divide-[var(--border-subtle)]">{filtered.map((source) => <div className="flex items-center gap-3 py-5" key={source.id}><Plug aria-hidden="true" size={20} /><button className="min-w-0 flex-1 text-left" onClick={() => setSelectedId(source.id)} type="button"><span className="block text-sm font-medium">{source.name}</span><span className="text-sm text-[var(--text-secondary)]">{source.provider} · {source.documents} documents · {source.scope}</span></button><Badge tone={source.status === "failed" ? "danger" : source.status === "syncing" ? "info" : "neutral"}>{source.status === "healthy" ? "Connected" : source.status}</Badge><span className="hidden text-xs text-[var(--text-tertiary)] xl:block">{source.lastSync}</span><Button aria-label={`Sync ${source.name}`} icon={<RefreshCw size={16} />} iconOnly variant="ghost" loading={source.status === "syncing"} onClick={() => sync(source)} /></div>)}{!filtered.length && <EmptyState title="No sources found" description="Add a source or try a different search." />}</div>;
}
