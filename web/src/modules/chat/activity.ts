import type { TurnArtifact } from "./artifacts";
import type { AnswerSource } from "./sources";

/**
 * A source opened for inspection beside the conversation.
 *
 * State stays at citation identity: the panel re-resolves the document through
 * the authorized knowledge API, so nothing here duplicates document content,
 * citation geometry, or storage locations.
 */
export interface KnowledgeDocumentActivity {
  type: "knowledge_document";
  citationId: string;
  itemId: string;
  chunkId: string;
  /** Shown in the panel header before the document resolves. */
  title: string;
  /** The cited page, when the answer's citation already names one. */
  page?: number;
}

/**
 * A document the assistant produced, opened for reading beside the chat.
 *
 * Only identity travels here: the panel fetches the revision's content through
 * the authorized artifact API, so nothing stored duplicates the document.
 */
export interface ArtifactPreviewActivity {
  type: "artifact";
  artifactId: string;
  title: string;
  revision: number;
}

export type RightActivity = KnowledgeDocumentActivity | ArtifactPreviewActivity;

/** Open one of a turn's documents in the activity panel. */
export function artifactPreviewActivity(artifact: TurnArtifact): ArtifactPreviewActivity {
  return {
    type: "artifact",
    artifactId: artifact.id,
    title: artifact.title,
    revision: artifact.revision,
  };
}

/** Open one of an answer's citations in the activity panel. */
export function knowledgeDocumentActivity(
  source: AnswerSource,
): KnowledgeDocumentActivity {
  return {
    type: "knowledge_document",
    citationId: source.id,
    itemId: source.itemId,
    chunkId: source.chunkId,
    title: source.title,
    page: source.page,
  };
}

/**
 * Whether the panel already shows this citation.
 *
 * Clicking the open citation again is a no-op rather than a reload, while a
 * different citation — including another one in the same document — replaces
 * the activity instead of stacking a second viewer.
 */
export function isSameActivity(
  current: RightActivity | null,
  next: RightActivity,
): boolean {
  if (!current || current.type !== next.type) return false;
  if (current.type === "artifact" && next.type === "artifact") {
    return current.artifactId === next.artifactId && current.revision === next.revision;
  }
  if (current.type !== "knowledge_document" || next.type !== "knowledge_document") {
    return false;
  }
  return (
    current.itemId === next.itemId
    && current.chunkId === next.chunkId
    && current.citationId === next.citationId
  );
}
