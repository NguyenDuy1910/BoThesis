"use client";

import {
  ExternalLink,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  PanelRight,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dropdown, DropdownItem, DropdownSeparator } from "@/components/ui/Dropdown";
import { Tabs } from "@/components/ui/Tabs";
import { Tooltip } from "@/components/ui/Tooltip";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { answerAvailability, documentFacts, documentStatus } from "@/modules/knowledge/document-facts";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

import { DocumentDetailsDrawer } from "./DocumentDetailsDrawer";
import { DocumentViewerContent } from "./DocumentViewerContent";
import { FileTypeIcon } from "./FileTypeIcon";

/**
 * The reader.
 *
 * One shell holds the identity, the actions, the two representations and the
 * page furniture; the format only decides what is drawn on the stage. Adding a
 * format is a renderer in `DocumentRenderers`, never another viewer.
 */
export function DocumentViewer({
  document,
  actions,
  onExpand,
  onClose,
  onReindex = () => undefined,
  onRequestRemove = () => undefined,
  expanded = false,
  showAgentView = true,
  showLifecycleActions = true,
}: {
  document: WorkspaceKnowledgeDocument;
  /** Surface-specific actions, shown before the shared overflow menu. */
  actions?: React.ReactNode;
  onExpand?: () => void;
  onClose?: () => void;
  onReindex?: () => void;
  onRequestRemove?: () => void;
  onToggleAnswerAvailability?: (included: boolean) => void;
  expanded?: boolean;
  showAgentView?: boolean;
  showLifecycleActions?: boolean;
}) {
  const [requestedView, setRequestedView] = useRouteState("view", "original");
  const view = requestedView === "agent" && showAgentView ? "agent" : "original";
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [search, setSearch] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    setPage(1);
    setZoom(100);
    setSearch("");
    setDetailsOpen(false);
  }, [document.id]);

  const facts = documentFacts(document);
  const status = documentStatus(document);

  return (
    <article aria-label={document.title} className="knowledge-viewer">
      <header className="knowledge-viewer__header">
        <FileTypeIcon className="mt-0.5" kind={document.kind} label={facts.fileTypeLabel} />
        <div className="min-w-0 flex-1">
          <h2 title={document.title}>{document.title}</h2>
          <p>{document.source} / {document.collection || "Unfiled"}</p>
        </div>
        <div className="knowledge-viewer__actions">
          {actions}
          {document.externalUrl && (
            <a className="knowledge-open-original" href={document.externalUrl} rel="noreferrer" target="_blank">
              <ExternalLink aria-hidden="true" size={16} />
              Open original
            </a>
          )}
        {showLifecycleActions && (
          <Dropdown
            align="right"
            ariaLabel={`Actions for ${document.title}`}
            buttonClassName="knowledge-icon-button knowledge-icon-button--sm"
            label={<MoreHorizontal aria-hidden="true" size={16} />}
            showChevron={false}
          >
            <DropdownItem disabled={document.state === "unsupported"} onClick={onReindex}>
              <RefreshCw aria-hidden="true" size={16} />Re-index document
            </DropdownItem>
            <DropdownSeparator />
            <DropdownItem destructive onClick={onRequestRemove}>
              <Trash2 aria-hidden="true" size={16} />Remove from knowledge
            </DropdownItem>
          </Dropdown>
        )}
          {onClose && (
            <Tooltip label="Close document" side="bottom">
              <Button
                aria-label="Close document"
                icon={<X size={16} />}
                iconOnly
                onClick={onClose}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
          )}
        </div>
      </header>

      <p className="knowledge-viewer__facts">
        <span>{document.pagesLabel} · {document.size} · updated {facts.modifiedLabel}</span>
        <span className={`knowledge-viewer__status knowledge-viewer__status--${status.tone}`}>
          <span aria-hidden="true" />{status.label}
        </span>
        <span>{answerAvailability(document)}</span>
      </p>

      <div className="knowledge-viewer__toolbar">
        {showAgentView && (
          <Tabs
            activeTab={view}
            ariaLabel="Document representation"
            density="compact"
            onChange={setRequestedView}
            tabs={[{ id: "original", label: "Original" }, { id: "agent", label: "Agent view" }]}
          />
        )}
        <div className="ml-auto flex items-center gap-1">
          <Button
            aria-expanded={detailsOpen}
            icon={<PanelRight size={16} />}
            onClick={() => setDetailsOpen((open) => !open)}
            selected={detailsOpen}
            size="sm"
            variant="ghost"
          >
            Details
          </Button>
          {onExpand && (
            <Tooltip label={expanded ? "Restore split view" : "Expand document"} side="bottom">
              <Button
                aria-label={expanded ? "Restore split view" : "Expand document"}
                icon={expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                iconOnly
                onClick={onExpand}
                size="sm"
                variant="ghost"
              />
            </Tooltip>
          )}
        </div>
      </div>

      <DocumentViewerContent
        document={document}
        key={document.id}
        onPageChange={setPage}
        onReindex={onReindex}
        onSearchChange={setSearch}
        onZoomChange={setZoom}
        page={page}
        search={search}
        view={view}
        zoom={zoom}
      />

      <DocumentDetailsDrawer
        document={document}
        onClose={() => setDetailsOpen(false)}
        onReindex={onReindex}
        onRequestRemove={onRequestRemove}
        open={detailsOpen}
        showLifecycleActions={showLifecycleActions}
      />
    </article>
  );
}
