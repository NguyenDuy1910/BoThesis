"use client";

import { ExternalLink, FileQuestion } from "lucide-react";
import { useEffect, useState } from "react";

import { Tabs } from "@/components/ui/Tabs";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

export interface RendererProps {
  document: WorkspaceKnowledgeDocument;
  page: number;
  /** Find-in-document. Empty when the reader is not searching. */
  search: string;
  /** Percent. Only the paged formats honour it. */
  zoom: number;
}

/**
 * Paints the matches of a find-in-document query.
 *
 * Highlighting is presentation, so it wraps rather than rewrites the text and
 * the underlying line is still selectable and readable by assistive tech.
 */
function Marked({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const parts = text.split(new RegExp(`(${needle.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)})`, "gi"));
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === needle.toLowerCase()
          ? <mark className="knowledge-mark" key={index}>{part}</mark>
          : <span key={index}>{part}</span>,
      )}
    </>
  );
}

/**
 * Three shapes of line, told apart the way a reader tells them apart: the
 * first all-caps line is the running head at the top of the page, a later
 * all-caps line is a section label, and a numbered line is a heading.
 */
function isAllCaps(line: string) {
  return line === line.toUpperCase() && /[A-Z]/.test(line);
}

function isHeading(line: string) {
  return /^\d+(\.\d+)*\s/.test(line) || /^(step|section|chapter)\b/i.test(line);
}

function DocumentBody({ lines, query }: { lines: string[]; query: string }) {
  return (
    <>
      {lines.map((line, index) =>
        isAllCaps(line) ? (
          <p
            className={index === 0 ? "knowledge-paper__running-head" : "knowledge-paper__label"}
            key={index}
          >
            <Marked query={query} text={line} />
          </p>
        ) : isHeading(line) ? (
          <h3 key={index}><Marked query={query} text={line} /></h3>
        ) : (
          <p key={index}><Marked query={query} text={line} /></p>
        ),
      )}
    </>
  );
}

/**
 * A PDF keeps its page furniture, because its pagination is real: a citation
 * that says page 12 has to be findable on page 12.
 */
export function PdfRenderer({ document, page, search, zoom }: RendererProps) {
  const lines = document.original;
  const matched = search ? lines.filter((line) => line.toLowerCase().includes(search.toLowerCase())) : lines;
  return (
    <article className="knowledge-paper" style={{ zoom: zoom / 100 }}>
      {matched.length ? (
        <DocumentBody lines={matched} query={search} />
      ) : (
        <p className="knowledge-paper__empty">No text on this page matches “{search}”.</p>
      )}
      <p className="knowledge-paper__folio">— {page} —</p>
    </article>
  );
}

/**
 * A Word file has no fixed pagination until it is printed, so it renders as
 * one readable column with no page furniture at all.
 */
export function DocxRenderer({ document, search }: RendererProps) {
  const lines = document.original;
  const matched = search ? lines.filter((line) => line.toLowerCase().includes(search.toLowerCase())) : lines;
  return (
    <article className="knowledge-paper knowledge-paper--flow">
      {matched.length ? (
        <DocumentBody lines={matched} query={search} />
      ) : (
        <p className="knowledge-paper__empty">Nothing in this document matches “{search}”.</p>
      )}
    </article>
  );
}

/**
 * A workbook renders as a grid with a sheet selector. What is readable here is
 * exactly what the agent indexed, which is why the cells are shown as cells
 * rather than flattened into prose.
 */
export function SpreadsheetRenderer({ document, search }: RendererProps) {
  const sheets = document.sheets ?? [];
  const [active, setActive] = useState(sheets[0]?.name ?? "");
  useEffect(() => setActive(sheets[0]?.name ?? ""), [document.id, sheets]);

  const sheet = sheets.find((item) => item.name === active) ?? sheets[0];
  if (!sheet) {
    return <p className="knowledge-paper__empty">This workbook has no readable sheet.</p>;
  }

  const rows = search
    ? sheet.rows.filter((row) => row.some((cell) => cell.toLowerCase().includes(search.toLowerCase())))
    : sheet.rows;

  return (
    <div className="knowledge-sheet">
      <div className="knowledge-sheet__grid">
        <table>
          <caption className="sr-only">{sheet.name}</caption>
          <thead>
            <tr>
              <th aria-label="Row" scope="col" />
              {sheet.columns.map((column, index) => (
                <th key={column} scope="col">
                  <span aria-hidden="true">{String.fromCharCode(65 + index)}</span>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <th scope="row">{rowIndex + 1}</th>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}><Marked query={search} text={cell} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="knowledge-paper__empty">No cell on this sheet matches “{search}”.</p>}
      </div>
      {sheets.length > 1 && (
        <div className="knowledge-sheet__tabs">
          <Tabs
            activeTab={sheet.name}
            ariaLabel="Workbook sheets"
            density="compact"
            onChange={setActive}
            tabs={sheets.map((item) => ({ id: item.name, label: item.name }))}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Preview is impossible, but the file is not a dead end: the source link and
 * the download still work, and the state says why it never answers.
 */
export function UnsupportedRenderer({ document }: RendererProps) {
  return (
    <div className="knowledge-unsupported">
      <FileQuestion aria-hidden="true" size={22} />
      <h3>Preview unavailable</h3>
      <p>
        {document.failureReason
          ?? `BoThesis cannot render ${document.fileTypeLabel ?? "this format"} files, so the document is stored but never used in answers.`}
      </p>
      {document.externalUrl && (
        <div className="knowledge-unsupported__actions">
          <a className="knowledge-open-original" href={document.externalUrl} rel="noreferrer" target="_blank">
            <ExternalLink aria-hidden="true" size={16} />
            Open in {document.source}
          </a>
        </div>
      )}
    </div>
  );
}

/**
 * Format to renderer. A new format is an entry here; nothing else changes.
 */
export const documentRenderers = {
  pdf: PdfRenderer,
  document: DocxRenderer,
  spreadsheet: SpreadsheetRenderer,
  unsupported: UnsupportedRenderer,
} as const;
