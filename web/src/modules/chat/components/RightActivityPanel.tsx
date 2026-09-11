"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { KnowledgeDocumentPreview } from "@/modules/knowledge/components/KnowledgeDocumentPreview";
import type { RightActivity } from "../activity";
import { ArtifactPreview } from "./ArtifactPreview";

/**
 * The contextual workspace beside the conversation.
 *
 * The chat stays the primary surface: this panel renders whichever activity is
 * open and is dismissed back to the full-width conversation, never navigated to.
 */
export function RightActivityPanel({
  activity,
  onClose,
  onAskSource,
}: {
  activity: RightActivity;
  onClose: () => void;
  onAskSource?: (title: string) => void;
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

  const isArtifact = activity.type === "artifact";
  const eyebrow = isArtifact ? "Document" : "Source of Truth";

  return (
    <aside aria-label={`${eyebrow} panel`} className="activity-panel">
      <header className="activity-panel__header">
        <div className="activity-panel__identity">
          <span className="activity-panel__eyebrow">{eyebrow}</span>
          <h2 className="activity-panel__title" title={activity.title}>{activity.title}</h2>
        </div>
        <button
          aria-label={`Close ${eyebrow.toLowerCase()} panel`}
          className="activity-panel__close"
          onClick={onClose}
          title="Close"
          type="button"
        >
          <X aria-hidden="true" size={16} />
        </button>
      </header>
      <div className="activity-panel__body">
        {activity.type === "artifact" ? (
          <ArtifactPreview
            artifactId={activity.artifactId}
            key={`${activity.artifactId}:${activity.revision}`}
            revision={activity.revision}
          />
        ) : (
          <KnowledgeDocumentPreview
            chunkId={activity.chunkId}
            // Keyed by document: two citations in one source reuse the loaded
            // viewer and just navigate, while another source starts clean.
            key={activity.itemId}
            itemId={activity.itemId}
            onAskSource={onAskSource}
            page={activity.page}
          />
        )}
      </div>
    </aside>
  );
}
