import type { StatusTone } from "@/components/patterns/StatusPill";

import type {
  KnowledgeAgentSection,
  WorkspaceKnowledgeDocument,
} from "./workspace-repository";

/**
 * One reading of a document, shared by the list, the viewer and the drawer.
 *
 * Records reach the interface from two places — the workspace snapshot, which
 * knows everything, and a personal upload, which knows only what the file
 * itself carries. Deriving the missing facts once, here, is what lets a single
 * row and a single viewer present both without either growing a branch.
 */
export interface DocumentFacts {
  fileTypeLabel: string;
  /** Pages for a document, sheets for a workbook. At least 1. */
  pageCount: number;
  /** "6 sheets" / "48 pages" — the unit that matches the format. */
  extentLabel: string;
  path: string;
  modifiedLabel: string;
  indexedLabel: string;
  sections: KnowledgeAgentSection[];
  /** Whether the format can be paged through at all. */
  pageable: boolean;
}

const KIND_LABEL = {
  pdf: "PDF",
  document: "Document",
  spreadsheet: "Spreadsheet",
  unsupported: "File",
} as const;

export function documentFacts(document: WorkspaceKnowledgeDocument): DocumentFacts {
  const extension = document.title.split(".").pop()?.toUpperCase();
  const fileTypeLabel =
    document.fileTypeLabel
    ?? (extension && extension.length <= 8 && extension !== document.title.toUpperCase()
      ? extension
      : KIND_LABEL[document.kind]);

  const parsedExtent = Number.parseInt(document.pagesLabel, 10);
  const pageCount = Math.max(1, document.pageCount ?? document.sheets?.length ?? (Number.isNaN(parsedExtent) ? 1 : parsedExtent));

  const sections = document.sections
    ?? document.agentView.map((line, index) => ({
      heading: index === 0 ? line : `Passage ${index}`,
      body: line,
    }));

  return {
    fileTypeLabel,
    pageCount,
    extentLabel: document.pagesLabel,
    path: document.path ?? document.collection ?? "Unfiled",
    modifiedLabel: document.modifiedAt ?? document.updatedLabel,
    indexedLabel: indexedLabel(document),
    sections,
    pageable: document.kind !== "unsupported" && document.state !== "restricted",
  };
}

function indexedLabel(document: WorkspaceKnowledgeDocument): string {
  switch (document.state) {
    case "indexed":
      return document.indexedAt ?? "Indexed";
    case "indexing":
      return "In progress";
    case "failed":
      return "Failed";
    case "restricted":
      return "Access lost";
    case "unsupported":
      return "Never indexed";
  }
}

export interface DocumentStatus {
  label: string;
  tone: StatusTone;
}

/**
 * How a document's lifecycle reads on a row.
 *
 * `unsupported` is deliberately neutral rather than red: nothing went wrong
 * and nothing can be retried, so an alarm colour would send the reader looking
 * for a fix that does not exist.
 */
export function documentStatus(document: WorkspaceKnowledgeDocument): DocumentStatus {
  switch (document.state) {
    case "indexed":
      return document.answerIncluded === false
        ? { label: "Excluded", tone: "neutral" }
        : { label: "Indexed", tone: "success" };
    case "indexing":
      return { label: "Indexing", tone: "warning" };
    case "failed":
      return { label: "Not indexed", tone: "danger" };
    case "restricted":
      return { label: "Restricted", tone: "warning" };
    case "unsupported":
      return { label: "Not indexed", tone: "neutral" };
  }
}

/** Whether grounded answers can quote this document right now. */
export function answerAvailability(document: WorkspaceKnowledgeDocument): string {
  if (document.state !== "indexed") return "Not available in answers";
  return document.answerIncluded === false ? "Excluded from answers" : "Included in answers";
}

/**
 * The supporting line under a document's name.
 *
 * Two things shape it. Inside a collection, the collection is already the
 * heading, so repeating it on every row spends the line on something the
 * reader just read. And the narrow layout has no date column, so the date
 * joins the line there and only there — never in both places at once.
 */
export function documentMeta(
  document: WorkspaceKnowledgeDocument,
  { scoped = false, layout = "full" }: { scoped?: boolean; layout?: "full" | "narrow" } = {},
): string {
  const facts = documentFacts(document);
  return [
    scoped ? null : document.source,
    scoped ? null : document.collection,
    facts.fileTypeLabel,
    document.pagesLabel,
    layout === "narrow" ? document.updatedLabel : null,
  ]
    .filter(Boolean)
    .join(" · ");
}
