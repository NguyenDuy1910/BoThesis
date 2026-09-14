"use client";
import { ChevronLeft, ChevronRight, Download, Info, Maximize2, Minimize2, Search, X, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Dialog } from "@/components/ui/Dialog";
import { Tabs } from "@/components/ui/Tabs";
import { SearchInput } from "@/components/ui/SearchInput";
import { EmptyState } from "@/components/ui/EmptyState";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";
import { FileTypeIcon } from "./FileTypeIcon";

/** Shared content viewer; feature-owned actions are supplied through the header slot. */
export function WorkspaceDocumentViewer({ document, actions, onExpand, onClose, expanded = false, showAgentView = true }: {
  document: WorkspaceKnowledgeDocument; actions?: React.ReactNode; onExpand?: () => void;
  onClose?: () => void; expanded?: boolean; showAgentView?: boolean;
}) {
  const [view, setView] = useState("original");
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [details, setDetails] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => { setPage(1); setView("original"); setSearch(""); }, [document.id]);
  const pages = Math.max(1, Number.parseInt(document.pagesLabel) || 1);
  const lines = view === "agent" ? document.agentView : document.original;
  const matched = !search ? lines : lines.filter((line) => line.toLowerCase().includes(search.toLowerCase()));
  const restricted = document.state === "restricted";
  const download = () => {
    const url = URL.createObjectURL(new Blob([document.original.join("\n\n")], { type: "text/plain" }));
    const anchor = window.document.createElement("a"); anchor.href = url; anchor.download = document.title + ".preview.txt"; anchor.click(); URL.revokeObjectURL(url);
  };
  return <article className="flex min-h-full flex-col" aria-label={document.title}>
    <header className="flex items-start gap-3 border-b border-[var(--border-subtle)] px-5 py-4">
      <FileTypeIcon kind={document.kind} />
      <div className="min-w-0 flex-1"><h2 className="truncate text-sm font-medium" title={document.title}>{document.title}</h2><p className="mt-1 truncate text-xs text-[var(--text-tertiary)]">{document.source} / {document.collection || "Library"}</p></div>
      {actions}
      {onClose && <Button aria-label="Close document" icon={<X size={16} />} iconOnly size="sm" variant="ghost" onClick={onClose} />}
    </header>
    <div className="flex flex-wrap items-center gap-2 px-5 py-3 text-xs text-[var(--text-tertiary)]">
      <span>{document.pagesLabel} · {document.size} · {document.updatedLabel}</span>
      <Badge tone={document.state === "indexed" ? "success" : document.state === "failed" ? "danger" : "neutral"}>{document.state === "indexed" ? "Available" : document.state === "restricted" ? "Access lost" : document.state === "failed" ? "Index failed" : "Indexing"}</Badge>
    </div>
    {restricted ? <EmptyState title="Access to this document has changed" description="Source permissions apply. Ask the source owner to restore access." /> : <>
      <div className="flex items-center gap-1 border-b border-[var(--border-subtle)] px-4 pb-2">
        {showAgentView && <Tabs activeTab={view} ariaLabel="Document representation" density="compact" onChange={setView} tabs={[{ id: "original", label: "Original" }, { id: "agent", label: "Agent view" }]} />}
        <div className="ml-auto flex gap-1">
          <Button aria-label="Search document" icon={<Search size={16} />} iconOnly variant="ghost" size="sm" onClick={() => setSearchOpen(!searchOpen)} />
          <Button aria-label="Document details" icon={<Info size={16} />} iconOnly variant="ghost" size="sm" onClick={() => setDetails(true)} />
          <Button aria-label="Download preview" icon={<Download size={16} />} iconOnly variant="ghost" size="sm" onClick={download} />
          {onExpand && <Button aria-label={expanded ? "Restore split view" : "Expand document"} icon={expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />} iconOnly variant="ghost" size="sm" onClick={onExpand} />}
        </div>
      </div>
      {searchOpen && <SearchInput ariaLabel="Find in document" className="m-3" debounceMs={0} value={search} onChange={setSearch} placeholder="Find in document…" />}
      {document.kind === "unsupported" ? <EmptyState title="Preview unavailable" description="This file type cannot be displayed. Download the preview information or choose another file." /> :
        <div className="min-h-0 flex-1 overflow-auto bg-[var(--surface-canvas)] p-5">
          <div className="document-paper" style={{ zoom: zoom / 100 }}>
            {view === "agent" && <p className="text-xs">Indexed sections · {lines.length} citation anchors</p>}
            {document.kind === "spreadsheet" && view === "original" ? <table className="w-full text-left text-sm"><caption className="pb-5 text-left font-medium">{document.title}</caption><tbody>{matched.filter((line) => line.includes("|")).map((line, index) => <tr key={index}>{line.split("|").map((cell, column) => index === 0 ? <th className="border-b border-[var(--border-subtle)] p-3" key={column}>{cell}</th> : <td className="border-b border-[var(--border-subtle)] p-3" key={column}>{cell}</td>)}</tr>)}</tbody></table> :
              matched.map((line, index) => index === 0 ? <h3 key={index}>{line}</h3> : <p key={index}>{line}{view === "agent" && <sup className="ml-2 text-[var(--text-accent)]">[{index}]</sup>}</p>)}
            {!matched.length && <p>No matching text.</p>}
            <p className="pt-10 text-center text-xs">Page {page}</p>
          </div>
        </div>}
      <footer className="sticky bottom-0 flex items-center justify-center gap-2 border-t border-[var(--border-subtle)] bg-[var(--surface-base)] p-2 text-sm">
        <Button aria-label="Previous page" icon={<ChevronLeft size={16} />} iconOnly size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)} /><span aria-live="polite">{page} / {pages}</span><Button aria-label="Next page" icon={<ChevronRight size={16} />} iconOnly size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)} />
        <Button aria-label="Zoom out" icon={<ZoomOut size={16} />} iconOnly size="sm" variant="ghost" disabled={zoom <= 50} onClick={() => setZoom(zoom - 10)} /><span>{zoom}%</span><Button aria-label="Zoom in" icon={<ZoomIn size={16} />} iconOnly size="sm" variant="ghost" disabled={zoom >= 150} onClick={() => setZoom(zoom + 10)} />
      </footer>
    </>}
    <Dialog title="Document details" open={details} onClose={() => setDetails(false)}>
      <dl className="grid grid-cols-[auto_1fr] gap-3 text-sm"><dt>Source</dt><dd>{document.source}</dd><dt>Collection</dt><dd>{document.collection || "None"}</dd><dt>Type</dt><dd>{document.kind}</dd><dt>Size</dt><dd>{document.size}</dd><dt>Updated</dt><dd>{document.updatedLabel}</dd><dt>Access</dt><dd>Source permissions apply</dd></dl>
    </Dialog>
  </article>;
}
