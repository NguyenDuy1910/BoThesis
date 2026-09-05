"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { KnowledgeDocumentPreview } from "@/modules/knowledge/components/KnowledgeDocumentPreview";
import type { RightActivity } from "../activity";

/**
 * The contextual workspace beside the conversation.
 *
 * The chat stays the primary surface: this panel renders whichever activity is
 * open and is dismissed back to the full-width conversation, never navigated to.
 */
export function RightActivityPanel({
  activity,
  onClose,
}: {
  activity: RightActivity;
  onClose: () => void;
}) {
  // Escape returns the reader to the full-width conversation, matching how the
  // conversation sidebar is dismissed.
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <aside aria-label="Source panel" className="activity-panel">
      <header className="activity-panel__header">
        <div className="activity-panel__identity">
          <span className="activity-panel__eyebrow">Source</span>
          <h2 className="activity-panel__title" title={activity.title}>{activity.title}</h2>
        </div>
        <button
          aria-label="Close source panel"
          className="activity-panel__close"
          onClick={onClose}
          title="Close"
          type="button"
        >
          <X aria-hidden="true" size={16} />
        </button>
      </header>
      <div className="activity-panel__body">
        <KnowledgeDocumentPreview
          chunkId={activity.chunkId}
          // Keyed by document: two citations in one source reuse the loaded
          // viewer and just navigate, while another source starts clean.
          key={activity.itemId}
          itemId={activity.itemId}
          page={activity.page}
        />
      </div>
    </aside>
  );
}
