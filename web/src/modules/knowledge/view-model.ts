/**
 * Turning the API's Items into what the Knowledge screen shows.
 *
 * The API answers in durable facts — an Item's status, its MIME type, when it
 * was last touched. A person reads "PDF · 1.1 MB · 2 days ago". Every such
 * phrase is derived here, in one place, so no screen invents one of its own
 * and no two screens word the same fact differently.
 */

import { fileKind, formatBytes, formatRelative } from "@/modules/admin/format";
import type {
  KnowledgeDocumentKind,
  KnowledgeDocumentState,
  WorkspaceKnowledgeCollection,
  WorkspaceKnowledgeDocument,
} from "@/modules/knowledge/workspace-repository";

export interface ApiKnowledgeSource {
  id: string;
  connector_key: string;
  display_name: string | null;
  external_url?: string | null;
}

export interface ApiKnowledgeDocument {
  id: string;
  title: string;
  content_type: string | null;
  document_type: string | null;
  status: "pending" | "processing" | "ready" | "failed" | "unsupported";
  updated_at: string;
  size_bytes?: number | null;
  source?: ApiKnowledgeSource | null;
}

export interface ApiKnowledgeCollection {
  id: string;
  title: string;
  description: string | null;
  parent_item_id: string | null;
  document_count: number;
  source_count: number;
  updated_at: string;
}

const SPREADSHEET = /sheet|excel|csv/i;
const PDF = /pdf/i;

/** What a person calls the format, from the MIME type or the file name. */
export function documentKind(document: ApiKnowledgeDocument): KnowledgeDocumentKind {
  const hint = `${document.content_type ?? ""} ${document.document_type ?? ""} ${document.title}`;
  if (PDF.test(hint)) return "pdf";
  if (SPREADSHEET.test(hint)) return "spreadsheet";
  if (document.status === "unsupported") return "unsupported";
  return "document";
}

/**
 * Indexing state, as the screen distinguishes it.
 *
 * `pending` and `processing` are both "working on it" to a reader waiting for
 * a document to become searchable, so they collapse to one word.
 */
export function documentState(document: ApiKnowledgeDocument): KnowledgeDocumentState {
  switch (document.status) {
    case "ready":
      return "indexed";
    case "failed":
      return "failed";
    case "unsupported":
      return "unsupported";
    default:
      return "indexing";
  }
}

export function toWorkspaceDocument(
  document: ApiKnowledgeDocument,
  collectionTitle: string,
): WorkspaceKnowledgeDocument {
  return {
    id: document.id,
    title: document.title,
    kind: documentKind(document),
    state: documentState(document),
    collection: collectionTitle,
    source: document.source?.display_name ?? "Uploaded to this workspace",
    updatedLabel: formatRelative(document.updated_at),
    size: formatBytes(document.size_bytes),
    // Page counts come from the document viewer, which reads the indexed
    // content. A list row must not claim a number nobody has counted.
    pagesLabel: "",
    fileTypeLabel: fileKind(document.title, document.document_type),
    externalUrl: document.source?.external_url ?? undefined,
    modifiedAt: document.updated_at,
    original: [],
    agentView: [],
  };
}

export function toWorkspaceCollection(
  collection: ApiKnowledgeCollection,
): WorkspaceKnowledgeCollection {
  return {
    id: collection.id,
    name: collection.title,
    source: collection.source_count
      ? `${collection.source_count} ${collection.source_count === 1 ? "source" : "sources"}`
      : "Direct uploads",
    kind: collection.source_count ? "folder" : "upload",
    documentCount: collection.document_count,
  };
}

/** The most recent change across the workspace, worded for the header. */
export function lastActivityLabel(collections: ApiKnowledgeCollection[]): string {
  const newest = collections
    .map((collection) => collection.updated_at)
    .filter(Boolean)
    .sort()
    .at(-1);
  return newest ? `updated ${formatRelative(newest)}` : "no activity yet";
}
