"use client";
import { ArrowLeft, Bookmark, FileText, FileSpreadsheet, Plus, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { SplitView } from "@/components/layout/SplitView";
import { CollectionRow, DocumentRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { Tabs } from "@/components/ui/Tabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { WorkspaceDocumentViewer } from "@/modules/knowledge/components/WorkspaceDocumentViewer";
import { useLibrary, libraryActions } from "./queries";

export function LibraryScreen() {
  const router = useRouter();
  const query = useLibrary();
  const [tab, setTab] = useRouteState("tab", "all");
  const [collection, setCollection] = useRouteState("collection");
  const [selectedId, setSelectedId] = useRouteState("document");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState("recent");
  const [expanded, setExpanded] = useState(false);
  const [create, setCreate] = useState<"collection" | "note" | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const documents = query.data?.documents ?? [];
  const collections = query.data?.collections ?? [];
  const selected = documents.find((item) => item.id === selectedId);
  const rows = documents.filter((item) =>
    (!collection || item.collection === collection) && (!source || (source === "personal" ? item.uploaded : item.saved)) &&
    (!type || item.kind === type) && (tab !== "uploads" || item.uploaded) && (tab !== "saved" || item.saved) &&
    item.title.toLowerCase().includes(search.toLowerCase())).sort((a, b) => sort === "name" ? a.title.localeCompare(b.title) : 0);
  const displayedCollections = collections.filter((item) => !search || item.name.toLowerCase().includes(search.toLowerCase()));
  const openCreate = (value: "collection" | "note") => { setCreate(value); setName(""); setContent(""); setError(null); };
  const list = <div className="px-[var(--page-gutter)] pb-5">
    {!selected && !collection && (tab === "all" || tab === "collections") && <>
      <h2 className="document-heading">Collections</h2>
      {displayedCollections.map((item) => <CollectionRow key={item.id} name={item.name} source={item.description} count={documents.filter((document) => document.collection === item.name).length} onOpen={() => setCollection(item.name)} />)}
    </>}
    {tab !== "collections" || collection ? <>
      <h2 className="document-heading">{collection || (selected ? "All items" : "Recent items")}</h2>
      {!rows.length ? <EmptyState title={search || source || type ? "No results" : "Your library is empty"} description={search || source || type ? "Try a different search or clear the filters." : "Upload a document or create your first collection."} action={<Button onClick={() => upload.current?.click()} variant="ghost">Upload a file</Button>} /> :
        rows.map((item) => <DocumentRow key={item.id} title={item.title} icon={item.kind === "spreadsheet" ? FileSpreadsheet : FileText} meta={item.source + (item.collection ? " · " + item.collection : "")} updated={item.updatedLabel} layout={selected ? "narrow" : "full"} selected={item.id === selectedId} status={item.state === "restricted" ? "Access lost" : item.saved ? "Saved" : "Personal"} statusTone={item.state === "restricted" ? "warning" : "neutral"} onSelect={() => { setSelectedId(item.id); setExpanded(false); }} />)}
    </> : null}
  </div>;
  return <section className="document-workspace" aria-label="Personal library">
    <div className="px-[var(--page-gutter)] pt-4">
      <Tabs activeTab={tab} ariaLabel="Library views" onChange={setTab} tabs={[{ id: "all", label: "All" }, { id: "collections", label: "Collections" }, { id: "uploads", label: "Uploads" }, { id: "saved", label: "Saved" }]} />
      <CommandBar search={{ value: search, onChange: setSearch, placeholder: "Search your library…", label: "Search your library" }}
        filters={<>
          <FilterTrigger label="Collection" value={collection} onChange={setCollection} options={[{ value: "", label: "All collections" }, ...collections.map((item) => ({ value: item.name, label: item.name }))]} />
          <FilterTrigger label="Source" value={source} onChange={setSource} options={[{ value: "", label: "Source" }, { value: "personal", label: "Uploaded by you" }, { value: "saved", label: "Saved from workspace" }]} />
          <FilterTrigger label="File type" value={type} onChange={setType} options={[{ value: "", label: "Type" }, { value: "pdf", label: "PDF" }, { value: "document", label: "Documents" }, { value: "spreadsheet", label: "Spreadsheets" }]} />
        </>} action={<>
          <FilterTrigger label="Sort library" value={sort} onChange={setSort} options={[{ value: "recent", label: "Recent" }, { value: "name", label: "Name" }]} />
          <Dropdown ariaLabel="Add to library" label={<Plus size={17} />} showChevron={false} buttonClassName="h-9 w-9 border-0 shadow-none p-0" title="Add to library"><DropdownItem onClick={() => openCreate("collection")}>New collection</DropdownItem><DropdownItem onClick={() => openCreate("note")}>Add note</DropdownItem></Dropdown>
          <Button aria-label="Upload to library" icon={<Upload size={17} />} iconOnly variant="ghost" loading={busy} onClick={() => upload.current?.click()} />
        </>} />
      {collection && <Button icon={<ArrowLeft size={15} />} variant="ghost" onClick={() => setCollection("")}>{collection}</Button>}
      {error && <ErrorState title="Action could not be completed" description={error} onAction={() => setError(null)} />}
      {query.error && <ErrorState title="Library could not be loaded" description={query.error} onAction={query.reload} />}
    </div>
    {query.loading ? <p className="p-6" role="status">Loading your library…</p> : <SplitView mode={selected ? expanded ? "detail" : "split" : "list"} list={list}
      detail={selected ? <WorkspaceDocumentViewer document={selected} showAgentView={false} expanded={expanded} onExpand={() => setExpanded(!expanded)} onClose={() => setSelectedId("")} actions={selected.state !== "restricted" ? <>
        <Button size="sm" variant="ghost" aria-label={selected.saved ? "Unsave document" : "Save document"} icon={<Bookmark size={15} fill={selected.saved ? "currentColor" : "none"} />} iconOnly onClick={() => libraryActions.save(selected.id, { saved: !selected.saved })} />
        <Button size="sm" onClick={() => router.push("/app?message=" + encodeURIComponent("Ask about " + selected.title))}>Ask BoThesis</Button>
      </> : null} /> : null} />}
    <input aria-label="Upload library file" type="file" className="hidden" ref={upload} onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; setBusy(true); setError(null); try { await libraryActions.upload(file, collection); } catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed."); } finally { setBusy(false); event.target.value = ""; } }} />
    <Dialog title={create === "collection" ? "New collection" : "Add note"} open={Boolean(create)} onClose={() => setCreate(null)}>
      <form className="grid gap-4" onSubmit={async (event) => { event.preventDefault(); setBusy(true); try { if (create === "collection") await libraryActions.createCollection(name.trim()); else await libraryActions.addNote(name.trim(), content, collection); setCreate(null); } finally { setBusy(false); } }}>
        <label className="configuration-field">Name<Input required autoFocus value={name} onChange={(event) => setName(event.target.value)} /></label>
        {create === "note" && <label className="configuration-field">Content<Textarea required rows={5} value={content} onChange={(event) => setContent(event.target.value)} /></label>}
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setCreate(null)}>Cancel</Button><Button type="submit" loading={busy} disabled={!name.trim()}>Create</Button></div>
      </form>
    </Dialog>
  </section>;
}
