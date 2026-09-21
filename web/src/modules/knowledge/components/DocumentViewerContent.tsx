"use client";

import { LockKeyhole, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { documentFacts } from "@/modules/knowledge/document-facts";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

import { AgentDocumentView } from "./AgentDocumentView";
import { DocumentPager } from "./DocumentPager";
import { documentRenderers } from "./DocumentRenderers";

interface DocumentViewerContentProps {
  document: WorkspaceKnowledgeDocument;
  page: number;
  search: string;
  view: "original" | "agent";
  zoom: number;
  onPageChange: (page: number) => void;
  onZoomChange: (zoom: number) => void;
  onSearchChange: (value: string) => void;
  onReindex: () => void;
}

/**
 * The stage.
 *
 * It decides three things and nothing else: whether there is anything to show
 * at all, which representation was asked for, and which renderer draws the
 * format. Everything a reader operates lives in the shell around it.
 */
export function DocumentViewerContent({
  document,
  page,
  search,
  view,
  zoom,
  onPageChange,
  onZoomChange,
  onSearchChange,
  onReindex,
}: DocumentViewerContentProps) {
  const facts = documentFacts(document);

  if (document.state === "restricted") {
    return (
      <div className="knowledge-viewer__stage">
        <EmptyState
          description={`Permissions in ${document.source} changed, so this document can no longer be read here. Its owner can restore access.`}
          icon={<LockKeyhole size={20} />}
          title="Access to this document has changed"
        />
      </div>
    );
  }

  const Renderer = documentRenderers[document.kind];
  const paged = document.kind === "pdf" && facts.pageCount > 1;
  const zoomable = document.kind === "pdf";

  return (
    <div className="knowledge-viewer__stage">
      {document.state === "failed" && (
        <div className="knowledge-notice knowledge-notice--danger" role="alert">
          <TriangleAlert aria-hidden="true" size={16} />
          <div>
            <strong>This document could not be indexed</strong>
            <p>{document.failureReason ?? "BoThesis could not read the file, so it never appears in an answer."}</p>
          </div>
          <Button onClick={onReindex} size="sm" variant="secondary">Retry</Button>
        </div>
      )}

      {view === "agent" ? (
        <AgentDocumentView document={document} search={search} />
      ) : (
        <Renderer document={document} page={page} search={search} zoom={zoom} />
      )}

      {view === "original" && (paged || zoomable) && (
        <DocumentPager
          onPageChange={onPageChange}
          onSearchChange={onSearchChange}
          onZoomChange={onZoomChange}
          page={page}
          pageCount={facts.pageCount}
          search={search}
          zoom={zoom}
        />
      )}
    </div>
  );
}
