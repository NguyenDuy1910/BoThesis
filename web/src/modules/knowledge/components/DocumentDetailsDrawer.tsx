"use client";

import { Eye, EyeOff, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/Button";
import { answerAvailability, documentFacts } from "@/modules/knowledge/document-facts";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

interface DocumentDetailsDrawerProps {
  document: WorkspaceKnowledgeDocument;
  open: boolean;
  onClose: () => void;
  onReindex?: () => void;
  onToggleAnswerAvailability?: (included: boolean) => void;
  onRequestRemove?: () => void;
  showLifecycleActions?: boolean;
}

/**
 * Everything about a document that is not the document.
 *
 * It docks beside the reader instead of covering it, because the reason to
 * open it is almost always to check a fact against what is on the page. That
 * makes it non-modal: no scrim, nothing behind it goes inert, and Escape
 * closes it — a dialog's manners would be wrong for a panel you read across.
 */
export function DocumentDetailsDrawer({
  document,
  open,
  onClose,
  onReindex,
  onToggleAnswerAvailability,
  onRequestRemove,
  showLifecycleActions = true,
}: DocumentDetailsDrawerProps) {
  const panelRef = useRef<HTMLElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = globalThis.document.activeElement as HTMLElement | null;
    panelRef.current?.querySelector<HTMLElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    globalThis.document.addEventListener("keydown", onKeyDown);
    return () => {
      globalThis.document.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus();
    };
  }, [onClose, open]);

  if (!open) return null;

  const facts = documentFacts(document);
  const answerIncluded = document.answerIncluded !== false;
  const indexed = document.state === "indexed";

  return (
    <aside aria-label="Document details" className="knowledge-details" ref={panelRef}>
      <header className="knowledge-details__header">
        <h3>Details</h3>
        <Button
          aria-label="Close details"
          icon={<X size={16} />}
          iconOnly
          onClick={onClose}
          size="sm"
          variant="ghost"
        />
      </header>

      <div className="knowledge-details__body">
        <dl className="knowledge-details__facts">
          <div><dt>Source</dt><dd>{document.source}</dd></div>
          <div><dt>Path</dt><dd>{facts.path}</dd></div>
          {document.owner && <div><dt>Owner</dt><dd>{document.owner}</dd></div>}
          <div><dt>Modified</dt><dd>{facts.modifiedLabel}</dd></div>
          <div><dt>Indexed</dt><dd>{facts.indexedLabel}</dd></div>
          <div><dt>File</dt><dd>{facts.fileTypeLabel} · {document.pagesLabel} · {document.size}</dd></div>
          <div>
            <dt>Search availability</dt>
            <dd className={indexed && answerIncluded ? "knowledge-details__value--ok" : undefined}>
              {answerAvailability(document)}
            </dd>
          </div>
        </dl>

        {(document.indexingNote || document.failureReason) && (
          <details className="knowledge-details__disclosure">
            <summary>Indexing</summary>
            <p>{document.indexingNote ?? document.failureReason}</p>
          </details>
        )}
      </div>

      {showLifecycleActions && (
        <footer className="knowledge-details__actions">
          <button
            disabled={document.state === "unsupported"}
            onClick={onReindex}
            type="button"
          >
            <RefreshCw aria-hidden="true" size={16} />Re-index document
          </button>
          <button
            disabled={!indexed}
            onClick={() => onToggleAnswerAvailability?.(!answerIncluded)}
            type="button"
          >
            {answerIncluded
              ? <><EyeOff aria-hidden="true" size={16} />Exclude from answers</>
              : <><Eye aria-hidden="true" size={16} />Include in answers</>}
          </button>
          <button className="knowledge-details__danger" onClick={onRequestRemove} type="button">
            <Trash2 aria-hidden="true" size={16} />Remove from knowledge
          </button>
        </footer>
      )}
    </aside>
  );
}
