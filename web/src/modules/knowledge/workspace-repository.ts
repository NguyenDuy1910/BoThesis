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

const regulationSections: KnowledgeAgentSection[] = [
  {
    heading: "4.2 Graduation requirements",
    body: "A student of the 2026 intake shall be eligible for graduation upon satisfying all of the following conditions: completion of 145 credits, including every core course and the capstone project; a cumulative grade point average of not less than 2.50 on the four-point scale; certification of English proficiency at TOEIC 500 or the internal equivalent, obtained before the thesis defence; no outstanding disciplinary measure recorded at the time of the graduation council.",
    page: 12,
    citedCount: 14,
  },
  {
    heading: "4.3 Thesis submission",
    body: "The thesis shall be submitted no later than 15 May 2026, being four weeks before the opening of the defence window on 12 June 2026. A submission received after this date shall be carried to the autumn session.",
    page: 12,
    citedCount: 9,
  },
  {
    heading: "4.4 Graduation council",
    body: "The graduation council shall convene twice in each academic year and shall confirm eligibility against the conditions set out in 4.2.",
    page: 12,
  },
];

const snapshot: KnowledgeWorkspaceSnapshot = {
  workspaceName: "SPKT Assistant",
  documentCount: 12_483,
  sourceCount: 4,
  lastSyncLabel: "synced 8 minutes ago",
  collections: [
    { name: "Policies", source: "Google Drive", kind: "folder", documentCount: 412 },
    { name: "Handbooks", source: "Google Drive", kind: "folder", documentCount: 1_208 },
    { name: "Course catalogues", source: "Google Drive", kind: "folder", documentCount: 6_584 },
    { name: "Uploaded files", source: "Direct upload · 42 people", kind: "upload", documentCount: 3_116 },
    { name: "University website", source: "Web crawl · hcmute.edu.vn", kind: "web", documentCount: 1_163 },
    { name: "Finance", source: "Google Drive", kind: "folder", documentCount: 1_204, restricted: true, owner: "Finance office" },
  ],
  documents: [
    {
      id: "academic-regulations",
      title: "Academic Regulations 2026.pdf",
      kind: "pdf",
      state: "indexed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Sep 11",
      size: "2.4 MB",
      pagesLabel: "48 pages",
      fileTypeLabel: "PDF",
      pageCount: 48,
      path: "Policies / 2026",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "academic.office@hcmute.edu.vn",
      modifiedAt: "11 Sep 2026 · 09:42",
      indexedAt: "11 Sep 2026 · 09:48",
      indexingNote: "48 of 48 pages read · text layer present · 312 passages extracted.",
      answerIncluded: true,
      original: [
        "HO CHI MINH CITY UNIVERSITY OF TECHNOLOGY AND EDUCATION",
        "CHAPTER 4 — GRADUATION",
        "4.2  Graduation requirements",
        "A student of the 2026 intake shall be eligible for graduation upon satisfying all of the following conditions:",
        "a)  completion of 145 credits, including every core course and the capstone project;",
        "b)  a cumulative grade point average of not less than 2.50 on the four-point scale;",
        "c)  certification of English proficiency at TOEIC 500 or the internal equivalent, obtained before the thesis defence;",
        "d)  no outstanding disciplinary measure recorded at the time of the graduation council.",
        "4.3  Thesis submission",
        "The thesis shall be submitted no later than 15 May 2026, being four weeks before the opening of the defence window on 12 June 2026. A submission received after this date shall be carried to the autumn session.",
      ],
      agentView: [],
      sections: regulationSections,
    },
    {
      id: "graduation-procedure",
      title: "Graduation Procedure — 2026 intake.docx",
      kind: "document",
      state: "indexed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Sep 10",
      size: "214 KB",
      pagesLabel: "12 pages",
      fileTypeLabel: "DOCX",
      pageCount: 12,
      path: "Policies / 2026",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "academic.office@hcmute.edu.vn",
      modifiedAt: "10 Sep 2026 · 15:10",
      indexedAt: "10 Sep 2026 · 15:12",
      indexingNote: "12 of 12 pages read · 64 passages extracted.",
      answerIncluded: true,
      original: [
        "Graduation Procedure",
        "2026 intake · Office of Academic Affairs",
        "1.  Before you apply",
        "Confirm with your faculty that all 145 credits are recorded, including the capstone project. Credits transferred from a partner university must already appear on your transcript.",
        "2.  Submitting the application",
        "Complete form TN-01 and have it signed by your supervisor.",
        "Attach your English proficiency certificate.",
        "Submit to the Academic Affairs office before 15 May 2026.",
      ],
      agentView: [],
      sections: [
        {
          heading: "1. Before you apply",
          body: "Confirm with your faculty that all 145 credits are recorded, including the capstone project. Credits transferred from a partner university must already appear on your transcript.",
          page: 2,
          citedCount: 6,
        },
        {
          heading: "2. Submitting the application",
          body: "Complete form TN-01 and have it signed by your supervisor, attach the English proficiency certificate, and submit to the Academic Affairs office before 15 May 2026.",
          page: 3,
          citedCount: 11,
        },
      ],
    },
    {
      id: "scholarship-criteria",
      title: "Scholarship Criteria v3.xlsx",
      kind: "spreadsheet",
      state: "indexing",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Sep 9",
      size: "88 KB",
      pagesLabel: "6 sheets",
      fileTypeLabel: "XLSX",
      pageCount: 6,
      path: "Policies / Scholarships",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "student.services@hcmute.edu.vn",
      modifiedAt: "9 Sep 2026 · 11:02",
      answerIncluded: true,
      original: [],
      agentView: [],
      sheets: [
        {
          name: "Criteria",
          columns: ["Programme", "Min GPA", "Award", "Quota"],
          rows: [
            ["Computer Engineering", "3.20", "50%", "12"],
            ["Mechanical Engineering", "3.00", "50%", "10"],
            ["Applied Mathematics", "3.40", "100%", "4"],
            ["Automotive Technology", "3.00", "30%", "15"],
          ],
        },
        {
          name: "Quotas",
          columns: ["Faculty", "Autumn", "Spring", "Total"],
          rows: [
            ["Engineering", "18", "14", "32"],
            ["Sciences", "9", "7", "16"],
            ["Economics", "6", "6", "12"],
          ],
        },
        {
          name: "2025 actuals",
          columns: ["Programme", "Awarded", "Declined", "Net"],
          rows: [
            ["Computer Engineering", "12", "1", "11"],
            ["Mechanical Engineering", "10", "0", "10"],
            ["Applied Mathematics", "4", "2", "2"],
          ],
        },
      ],
      sections: [
        {
          heading: "Criteria",
          body: "Award thresholds by programme: Computer Engineering 3.20 GPA at 50%, Mechanical Engineering 3.00 at 50%, Applied Mathematics 3.40 at 100%, Automotive Technology 3.00 at 30%.",
          page: 1,
        },
      ],
    },
    {
      id: "student-handbook",
      title: "Student Handbook 2025.pdf",
      kind: "pdf",
      state: "indexed",
      collection: "Handbooks",
      source: "Google Drive",
      updatedLabel: "Sep 4",
      size: "8.1 MB",
      pagesLabel: "214 pages",
      fileTypeLabel: "PDF",
      pageCount: 214,
      path: "Handbooks / 2025",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "student.services@hcmute.edu.vn",
      modifiedAt: "4 Sep 2026 · 08:30",
      indexedAt: "4 Sep 2026 · 08:51",
      indexingNote: "214 of 214 pages read · 1,486 passages extracted.",
      answerIncluded: true,
      original: [
        "STUDENT HANDBOOK 2025",
        "SECTION 1 — STUDENT SERVICES",
        "1.1  Academic support",
        "This handbook explains the academic, conduct and support services available to enrolled students.",
        "Students should consult the relevant policy owner when a local procedure differs from this handbook.",
        "1.2  Conduct",
        "Disciplinary measures are recorded against the student record and are considered at the graduation council.",
      ],
      agentView: [],
      sections: [
        {
          heading: "1.1 Academic support",
          body: "The handbook explains the academic, conduct and support services available to enrolled students, and directs a reader to the policy owner whenever a local procedure differs.",
          page: 4,
          citedCount: 23,
        },
        {
          heading: "1.2 Conduct",
          body: "Disciplinary measures are recorded against the student record and are considered at the graduation council.",
          page: 9,
          citedCount: 5,
        },
      ],
    },
    {
      id: "transfer-credit-matrix",
      title: "Transfer Credit Matrix.numbers",
      kind: "unsupported",
      state: "unsupported",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Aug 22",
      size: "412 KB",
      pagesLabel: "Apple Numbers",
      fileTypeLabel: "NUMBERS",
      path: "Policies / Transfers",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "registrar@hcmute.edu.vn",
      modifiedAt: "22 Aug 2026 · 16:44",
      failureReason:
        "BoThesis cannot render Apple Numbers files and cannot read their contents. The document is stored, but it never appears in answers. Export it as XLSX or PDF to make it answerable.",
      answerIncluded: false,
      original: [],
      agentView: [],
    },
    {
      id: "admissions-draft",
      title: "Admissions Policy — DRAFT.pdf",
      kind: "pdf",
      state: "failed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Sep 12",
      size: "1.7 MB",
      pagesLabel: "22 pages",
      fileTypeLabel: "PDF",
      pageCount: 22,
      path: "Policies / Drafts",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "admissions@hcmute.edu.vn",
      modifiedAt: "12 Sep 2026 · 10:15",
      failureReason:
        "It is password protected, so BoThesis cannot read it. You can still open and download it, but it will never appear in an answer until the protection is removed.",
      indexingNote: "Extraction stopped at page 1 · pdf_encrypted · no text layer available.",
      answerIncluded: false,
      original: [
        "ADMISSIONS POLICY — DRAFT",
        "This file remains available for review, but it is password protected.",
      ],
      agentView: [],
    },
    {
      id: "enrolment-guide",
      title: "Enrolment Guide 2026.pdf",
      kind: "pdf",
      state: "indexed",
      collection: "Handbooks",
      source: "Google Drive",
      updatedLabel: "Sep 2",
      size: "3.2 MB",
      pagesLabel: "31 pages",
      fileTypeLabel: "PDF",
      pageCount: 31,
      path: "Handbooks / 2026",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "admissions@hcmute.edu.vn",
      modifiedAt: "2 Sep 2026 · 13:05",
      indexedAt: "2 Sep 2026 · 13:11",
      indexingNote: "31 of 31 pages read · 208 passages extracted.",
      answerIncluded: true,
      original: [
        "ENROLMENT GUIDE 2026",
        "STEP 1 — CONFIRM YOUR OFFER",
        "Accept the offer in the admissions portal within fourteen days of the offer date.",
        "STEP 2 — PAY THE ENROLMENT FEE",
        "The enrolment fee is due before the first teaching week and is set out in the fee schedule.",
      ],
      agentView: [],
      sections: [
        {
          heading: "Step 1 — Confirm your offer",
          body: "Accept the offer in the admissions portal within fourteen days of the offer date.",
          page: 3,
          citedCount: 8,
        },
        {
          heading: "Step 2 — Pay the enrolment fee",
          body: "The enrolment fee is due before the first teaching week and is set out in the fee schedule.",
          page: 5,
          citedCount: 4,
        },
      ],
    },
    {
      id: "fee-schedule",
      title: "Fee Schedule 2026.xlsx",
      kind: "spreadsheet",
      state: "indexed",
      collection: "Policies",
      source: "Google Drive",
      updatedLabel: "Aug 30",
      size: "64 KB",
      pagesLabel: "4 sheets",
      fileTypeLabel: "XLSX",
      pageCount: 4,
      path: "Policies / Fees",
      externalUrl: "https://drive.google.com/drive/my-drive",
      owner: "finance.office@hcmute.edu.vn",
      modifiedAt: "30 Aug 2026 · 09:20",
      indexedAt: "30 Aug 2026 · 09:22",
      indexingNote: "4 of 4 sheets read · 96 passages extracted.",
      answerIncluded: true,
      original: [],
      agentView: [],
      sheets: [
        {
          name: "Tuition",
          columns: ["Programme", "Per credit", "Full year", "Currency"],
          rows: [
            ["Computer Engineering", "820,000", "24,600,000", "VND"],
            ["Mechanical Engineering", "780,000", "23,400,000", "VND"],
            ["Applied Mathematics", "720,000", "21,600,000", "VND"],
          ],
        },
        {
          name: "Other fees",
          columns: ["Fee", "Amount", "When", "Refundable"],
          rows: [
            ["Enrolment", "500,000", "Before week 1", "No"],
            ["Library deposit", "300,000", "On enrolment", "Yes"],
            ["Re-sit", "250,000", "Per attempt", "No"],
          ],
        },
      ],
      sections: [
        {
          heading: "Tuition",
          body: "Per-credit and full-year tuition by programme, in VND, for the 2026 intake.",
          page: 1,
          citedCount: 17,
        },
      ],
    },
    {
      id: "research-archive",
      title: "Research archive.zip",
      kind: "unsupported",
      state: "restricted",
      collection: "Finance",
      source: "SharePoint",
      updatedLabel: "Sep 6",
      size: "42 MB",
      pagesLabel: "Archive",
      fileTypeLabel: "ZIP",
      path: "Finance / Archive",
      owner: "finance.office@hcmute.edu.vn",
      modifiedAt: "6 Sep 2026 · 17:30",
      answerIncluded: false,
      original: [],
      agentView: [],
    },
  ],
};

/** Temporary query boundary; a later HTTP implementation keeps this contract. */
export const knowledgeWorkspaceRepository = {
  async getSnapshot(): Promise<KnowledgeWorkspaceSnapshot> {
    return structuredClone(snapshot);
  },
};
