"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { DirectoryRow } from "@/components/patterns";
import { CommandBar } from "@/components/layout/CommandBar";
import { Tabs } from "@/components/ui/Tabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useWorkspaces } from "@/modules/auth/queries";
import { switchWorkspace } from "@/modules/auth/api";

export function WorkspaceDiscovery() {
  const router = useRouter();
  const query = useWorkspaces();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("for-you");
  const [error, setError] = useState<string | null>(null);
  const rows = (query.data ?? []).filter((item) => item.status === "active" && (item.member || item.discoverable) && (tab !== "organizations" || item.member) && `${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase()));
  return <section className="mx-auto w-full max-w-6xl p-[var(--page-gutter)]" aria-label="Explore workspaces">
    <h1 className="mb-5 text-[length:var(--text-size-h2)] font-semibold">Explore workspaces</h1>
    <CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search workspaces…", label: "Search workspaces" }} filters={<Tabs ariaLabel="Workspace discovery" activeTab={tab} onChange={setTab} tabs={[{ id: "for-you", label: "For you" }, { id: "organizations", label: "Your organizations" }, { id: "all", label: "All" }]} />} />
    {error || query.error ? <ErrorState title="Workspace could not be opened" description={error ?? query.error ?? ""} onAction={() => { setError(null); query.reload(); }} /> : null}
    {query.loading ? <p role="status">Loading workspaces…</p> : !rows.length ? <EmptyState title="No workspaces found" description="Try a different search or filter." /> : <div className="divide-y divide-[var(--border-subtle)]">{rows.map((item) => <DirectoryRow key={item.id} title={item.name} description={item.description} provider={`Provided by ${item.organization} · ${item.member ? "You are a member" : "Any signed-in user"}`} onOpen={async () => { try { await switchWorkspace(item.id); router.push("/app?action=new"); } catch (cause) { setError(cause instanceof Error ? cause.message : "Access unavailable."); } }} />)}</div>}
  </section>;
}
