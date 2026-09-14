"use client";
import { ArrowLeft, Plus, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { SplitView } from "@/components/layout/SplitView";
import { CollectionRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tabs } from "@/components/ui/Tabs";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { useKnowledge, knowledgeActions } from "@/modules/knowledge/queries";
import { WorkspaceDocumentRow } from "./WorkspaceDocumentRow";
import { WorkspaceDocumentViewer } from "./WorkspaceDocumentViewer";
import { KnowledgeSources } from "./KnowledgeSources";

export function WorkspaceKnowledgeScreen() {
  const query = useKnowledge();
  const [tab, setTab] = useRouteState("tab", "documents");
  const [selectedId, setSelectedId] = useRouteState("document");
  const [scope, setScope] = useRouteState("scope");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState("recent");
  const [expanded, setExpanded] = useState(false);
  const [addingSource, setAddingSource] = useState(false);
  const [provider, setProvider] = useState("Google Drive");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const all = query.data?.documents ?? [];
  const selected = all.find((item) => item.id === selectedId);
  const collections = [...new Set(all.map((item) => item.collection))];
  const rows = all.filter((item) => (!scope || item.collection === scope) && (!status || item.state === status) && (!type || item.kind === type) && item.title.toLowerCase().includes(search.toLowerCase())).sort((a, b) => sort === "name" ? a.title.localeCompare(b.title) : 0);
  const list = <div className="px-3 pb-5">
    {!selected && !scope && !search && <><h2 className="document-heading">Collections</h2>{collections.map((collection) => <CollectionRow key={collection} name={collection} source={all.find((item) => item.collection === collection)?.source ?? ""} count={all.filter((item) => item.collection === collection).length} onOpen={() => setScope(collection)} />)}</>}
    <h2 className="document-heading">{scope || "Recently updated"}</h2>
    {rows.map((document) => <WorkspaceDocumentRow document={document} key={document.id} onSelect={() => { setSelectedId(document.id); setExpanded(false); }} selected={document.id === selectedId} />)}
    {!rows.length && <EmptyState title="No documents found" description="Try a different search or broaden the filters." action={<Button variant="ghost" onClick={() => { setSearch(""); setStatus(""); setType(""); setScope(""); }}>Clear filters</Button>} />}
  </div>;
  return <section className="document-workspace" aria-label="Workspace knowledge">
    <Tabs activeTab={tab} ariaLabel="Knowledge views" onChange={setTab} tabs={[{ id: "documents", label: "Documents" }, { id: "sources", label: "Sources" }, { id: "activity", label: "Sync activity" }]} />
    <CommandBar search={{ value: search, onChange: setSearch, placeholder: tab === "documents" ? "Search knowledge…" : "Search sources…", label: "Search workspace knowledge" }}
      filters={tab === "documents" && <>
        <FilterTrigger label="Knowledge scope" value={scope} onChange={setScope} options={[{ value: "", label: "Scope: All knowledge" }, ...collections.map((item) => ({ value: item, label: item }))]} />
        <FilterTrigger label="Document status" value={status} onChange={setStatus} options={[{ value: "", label: "Status" }, { value: "indexed", label: "Indexed" }, { value: "indexing", label: "Indexing" }, { value: "failed", label: "Index failed" }, { value: "restricted", label: "Restricted" }]} />
        <FilterTrigger label="Document type" value={type} onChange={setType} options={[{ value: "", label: "Type" }, { value: "pdf", label: "PDF" }, { value: "document", label: "Documents" }, { value: "spreadsheet", label: "Spreadsheets" }, { value: "unsupported", label: "Unsupported" }]} />
      </>} action={<>
        <FilterTrigger label="Sort knowledge" value={sort} onChange={setSort} options={[{ value: "recent", label: "Recently updated" }, { value: "name", label: "Name" }]} />
        <Button aria-label="Add source" icon={<Plus size={17} />} iconOnly variant="ghost" onClick={() => setAddingSource(true)} />
        <Button aria-label="Upload knowledge files" icon={<Upload size={17} />} iconOnly variant="ghost" loading={busy} onClick={() => upload.current?.click()} />
      </>} />
    {scope && tab === "documents" && <Button className="self-start mb-2" icon={<ArrowLeft size={15} />} variant="ghost" onClick={() => setScope("")}>All knowledge / {scope}</Button>}
    {query.error || error ? <ErrorState title="Knowledge action failed" description={error ?? query.error ?? ""} onAction={() => { setError(null); query.reload(); }} /> : null}
    {query.loading ? <p className="p-5" role="status">Loading knowledge…</p> : tab !== "documents" ? <KnowledgeSources sources={query.data?.sources ?? []} runs={query.data?.runs ?? []} search={search} activity={tab === "activity"} /> :
      <SplitView mode={selected ? expanded ? "detail" : "split" : "list"} list={list} detail={selected ? <WorkspaceDocumentViewer document={selected} onClose={() => setSelectedId("")} expanded={expanded} onExpand={() => setExpanded(!expanded)} actions={<Dropdown ariaLabel="Document administration" label="More" buttonClassName="border-0 shadow-none"><DropdownItem onClick={() => knowledgeActions.reindex(selected.id)}>Re-index document</DropdownItem></Dropdown>} /> : null} />}
    <input type="file" aria-label="Upload knowledge file" className="hidden" ref={upload} onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; setBusy(true); try { await knowledgeActions.upload(file); } catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed."); } finally { setBusy(false); event.target.value = ""; } }} />
    <Dialog title="Add source" open={addingSource} onClose={() => setAddingSource(false)}>
      <form className="grid gap-4" onSubmit={async (event) => { event.preventDefault(); setBusy(true); try { await knowledgeActions.addSource(provider, name); setAddingSource(false); setName(""); setTab("sources"); } finally { setBusy(false); } }}>
        <label className="configuration-field">Provider<Select value={provider} onChange={(event) => setProvider(event.target.value)} options={["Google Drive", "Confluence", "SharePoint", "Slack", "Jira", "Website"].map((value) => ({ value, label: value }))} /></label>
        <label className="configuration-field">Source name<Input required value={name} onChange={(event) => setName(event.target.value)} /></label>
        <p className="text-sm text-[var(--text-secondary)]">Read-only access. Original source permissions remain authoritative.</p>
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setAddingSource(false)}>Cancel</Button><Button disabled={!name.trim()} loading={busy} type="submit">Add source</Button></div>
      </form>
    </Dialog>
  </section>;
}
