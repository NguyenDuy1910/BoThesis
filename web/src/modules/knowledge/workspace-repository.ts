export type KnowledgeDocumentKind = "pdf" | "document" | "spreadsheet" | "unsupported";
export type KnowledgeDocumentState = "indexed" | "indexing" | "failed" | "restricted";

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
  original: string[];
  agentView: string[];
}

export interface KnowledgeWorkspaceSnapshot {
  workspaceName: string;
  documentCount: number;
  sourceCount: number;
  documents: WorkspaceKnowledgeDocument[];
}

const snapshot: KnowledgeWorkspaceSnapshot = {
  workspaceName: "SPKT Assistant",
  documentCount: 412,
  sourceCount: 6,
  documents: [
    {
      id: "student-handbook",
      title: "Student Handbook 2025.pdf",
      kind: "pdf",
      state: "indexed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Updated 4 Sep",
      size: "8.1 MB",
      pagesLabel: "214 pages",
      original: ["Student Handbook 2025", "This handbook explains the academic, conduct, and support services available to enrolled students.", "Students should consult the relevant policy owner when a local procedure differs from this handbook."],
      agentView: ["What the assistant can use", "The handbook is indexed and may support grounded answers about student services, conduct, and academic procedures.", "Evidence is cited back to the page and passage that support an answer."],
    },
    {
      id: "graduation-procedure",
      title: "Graduation Procedure — 2026 intake.docx",
      kind: "document",
      state: "indexed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Updated 10 Sep",
      size: "241 KB",
      pagesLabel: "12 pages",
      original: ["Graduation Procedure", "Candidates complete the clearance, faculty verification, and submission steps in the stated order.", "The final timeline is published by Academic Affairs for each intake."],
      agentView: ["What the assistant can use", "This procedure provides the ordered steps and owner responsibilities for the 2026 intake.", "Answers should state that deadlines are intake-specific."],
    },
    {
      id: "scholarship-criteria",
      title: "Scholarship Criteria v3.xlsx",
      kind: "spreadsheet",
      state: "indexed",
      collection: "Finance",
      source: "Google Drive",
      updatedLabel: "Updated 9 Sep",
      size: "96 KB",
      pagesLabel: "6 sheets",
      original: ["Scholarship criteria", "Award type | Eligibility | Review owner", "Merit award | GPA and conduct threshold | Student Services"],
      agentView: ["What the assistant can use", "The workbook defines award types, eligibility conditions, and review owners across six sheets.", "The assistant cites the relevant sheet and rows when comparing criteria."],
    },
    {
      id: "admissions-draft",
      title: "Admissions Policy — DRAFT.pdf",
      kind: "pdf",
      state: "failed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Updated 12 Sep",
      size: "1.7 MB",
      pagesLabel: "22 pages",
      original: ["Admissions Policy — DRAFT", "This file remains available for review, but is password protected."],
      agentView: ["This document is not available to the assistant", "Remove password protection and re-index the document before it can appear in an answer."],
    },
    {
      id: "research-archive",
      title: "Research archive.zip",
      kind: "unsupported",
      state: "indexing",
      collection: "Research",
      source: "SharePoint",
      updatedLabel: "Updated 11 Sep",
      size: "42 MB",
      pagesLabel: "Unsupported archive",
      original: ["Preview unavailable", "This file type cannot be rendered in the knowledge viewer."],
      agentView: ["The assistant is waiting", "The source is still being inspected. Its contents will not be used until indexing completes."],
    },
  ],
};

/** Temporary query boundary; a later HTTP implementation keeps this contract. */
export const knowledgeWorkspaceRepository = {
  async getSnapshot(): Promise<KnowledgeWorkspaceSnapshot> {
    return structuredClone(snapshot);
  },
};
