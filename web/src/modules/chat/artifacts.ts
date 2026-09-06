import { isMessageItem, isOutputTextPart, orderedTurnItems } from "./message-stream.ts";
import { ARTIFACT_ANNOTATION_TYPE } from "./types.ts";
import type { ArtifactReference, TurnState } from "./types";

/** One document a turn created or revised, as the answer presents it. */
export interface TurnArtifact {
  id: string;
  title: string;
  fileName: string;
  mimeType: string;
  revision: number;
  sizeBytes: number;
  updatedAt: string;
  /** Export formats already rendered for this revision, e.g. `["pdf"]`. */
  exports: string[];
}

/**
 * Collect the artifacts from output-text annotations, never from stream events.
 *
 * A turn may present the same document more than once (a commentary and the
 * final answer, or two edits in one turn); each document is returned once in
 * first-cited order, carrying its newest revision.
 */
export function turnArtifacts(turn: TurnState | undefined): TurnArtifact[] {
  if (!turn) return [];
  const artifacts = new Map<string, TurnArtifact>();
  const order: string[] = [];

  for (const { item } of orderedTurnItems(turn)) {
    if (!isMessageItem(item)) continue;
    for (const part of item.content) {
      if (!isOutputTextPart(part)) continue;
      for (const annotation of part.annotations) {
        if (annotation.type !== ARTIFACT_ANNOTATION_TYPE || !annotation.artifact) continue;
        const artifact = toTurnArtifact(annotation.artifact);
        if (!artifact) continue;
        const existing = artifacts.get(artifact.id);
        if (!existing) {
          artifacts.set(artifact.id, artifact);
          order.push(artifact.id);
        } else if (artifact.revision >= existing.revision) {
          artifacts.set(artifact.id, artifact);
        }
      }
    }
  }
  return order.map((id) => artifacts.get(id)!);
}

function toTurnArtifact(reference: ArtifactReference): TurnArtifact | null {
  const id = reference.id?.trim();
  if (!id) return null;
  const revision = Number(reference.revision);
  return {
    id,
    title: reference.title?.trim() || reference.file_name?.trim() || "Untitled document",
    fileName: reference.file_name?.trim() || "document.md",
    mimeType: reference.mime_type?.trim() || "text/markdown",
    revision: Number.isFinite(revision) && revision >= 1 ? revision : 1,
    sizeBytes: Number.isFinite(Number(reference.size_bytes)) ? Number(reference.size_bytes) : 0,
    updatedAt: reference.updated_at ?? "",
    exports: Array.isArray(reference.exports)
      ? reference.exports.filter((value): value is string => typeof value === "string")
      : [],
  };
}

export function artifactSizeLabel(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function artifactFormatLabel(mimeType: string): string {
  if (mimeType === "text/markdown" || mimeType === "text/x-markdown") return "Markdown";
  if (mimeType === "application/pdf") return "PDF";
  if (mimeType.startsWith("text/")) return "Text";
  return "Document";
}
