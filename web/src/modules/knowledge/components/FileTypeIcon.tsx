import { File, FileSpreadsheet, FileText } from "lucide-react";

import type { KnowledgeDocumentKind } from "@/modules/knowledge/workspace-repository";

export function FileTypeIcon({ kind }: { kind: KnowledgeDocumentKind }) {
  const Icon = kind === "spreadsheet" ? FileSpreadsheet : kind === "document" ? FileText : File;
  const color = kind === "spreadsheet"
    ? "text-[var(--status-success-solid)] bg-[var(--status-success-bg)]"
    : kind === "unsupported"
      ? "text-[var(--status-warning-text)] bg-[var(--status-warning-bg)]"
      : "text-[var(--text-accent)] bg-[var(--accent-soft)]";
  return <span aria-hidden="true" className={`grid h-8 w-8 shrink-0 place-items-center rounded-[var(--radius-sm)] ${color}`}><Icon size={16} /></span>;
}
