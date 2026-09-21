/**
 * The view model the Knowledge screen renders.
 *
 * These describe how a document is shown, not how it is stored: the API
 * returns Items, and `knowledge/view-model.ts` maps one onto the other. The
 * split exists because the screen shows a person "18 pages · 1.1 MB · synced
 * 8 minutes ago", and none of those are columns.
 */
export type KnowledgeDocumentKind = "pdf" | "document" | "spreadsheet" | "unsupported";

/**
 * Where a document sits in its own lifecycle.
 *
 * `unsupported` is separate from `failed` on purpose: a failed index can be
 * retried and may succeed, while an unsupported format never will. Offering
 * "Re-index" for the second one would be a lie.
 */
export type KnowledgeDocumentState =
  | "indexed"
  | "indexing"
  | "failed"
  | "restricted"
  | "unsupported";

/** One retrievable passage, as the agent holds it. */
export interface KnowledgeAgentSection {
  heading: string;
  body: string;
  page?: number;
  /** How often answers have quoted this passage. Omitted when never quoted. */
  citedCount?: number;
}

export interface KnowledgeSheet {
  name: string;
  columns: string[];
  rows: string[][];
}

export interface WorkspaceKnowledgeDocument {
  id: string;
  title: string;
  kind: KnowledgeDocumentKind;
  state: KnowledgeDocumentState;
  collection: string;
  source: string;
  updatedLabel: string;
  size: string;
  pagesLabel: string;
  /** Whether grounded answers may use this document once it is indexed. */
  answerIncluded?: boolean;
  /** A lifecycle tombstone. Normal workspace reads exclude this document. */
  removedAt?: string;
  original: string[];
  agentView: string[];

  /* Everything below is optional so the personal Library, which builds these
     records from an upload, keeps working without inventing values it has no
     way to know. Each has a derivation in `documentFacts`. */

  /** "PDF", "DOCX", "XLSX" — the word a person uses for the format. */
  fileTypeLabel?: string;
  /** Pages for a document, sheets for a workbook. Drives the pager. */
  pageCount?: number;
  /** Where the document lives inside its source. */
  path?: string;
  /** The file in its own source. Absent for anything with no home to open. */
  externalUrl?: string;
  owner?: string;
  modifiedAt?: string;
  indexedAt?: string;
  /** Why indexing cannot succeed, stated in the viewer above the content. */
  failureReason?: string;
  /** Diagnostics, kept behind a disclosure in the details drawer. */
  indexingNote?: string;
  /** Retrieval-ready passages. Falls back to `agentView` lines. */
  sections?: KnowledgeAgentSection[];
  sheets?: KnowledgeSheet[];
}

export interface WorkspaceKnowledgeCollection {
  /** The Collection Item this row stands for. Uploads are addressed by it. */
  id: string;
  /** Matches `WorkspaceKnowledgeDocument.collection`; it is also the scope key. */
  name: string;
  /** Where the collection comes from, in one short phrase. */
  source: string;
  kind: "folder" | "upload" | "web";
  documentCount: number;
  /**
   * Visible but not openable. The count still reconciles with the workspace
   * total, which is why the row stays rather than being filtered away.
   */
  restricted?: boolean;
  owner?: string;
}

export interface KnowledgeWorkspaceSnapshot {
  workspaceName: string;
  documentCount: number;
  sourceCount: number;
  lastSyncLabel: string;
  collections: WorkspaceKnowledgeCollection[];
  documents: WorkspaceKnowledgeDocument[];
}
