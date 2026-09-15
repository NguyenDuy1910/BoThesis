import { FileSpreadsheet, FileText, FileType2, Files } from "lucide-react";

import { cn } from "@/lib/cn";
import type { KnowledgeDocumentKind } from "@/modules/knowledge/workspace-repository";

/**
 * A document's format, as a mark.
 *
 * It reuses the `.resource-icon` tones the conversation surface already uses
 * for attachments, so a PDF looks the same wherever it is listed. The tinting
 * is a format convention, not a status: the row's status signal sits on the
 * opposite edge, where it cannot be confused with this.
 */
const presentation = {
  pdf: { Icon: FileType2, tone: "pdf", label: "PDF" },
  document: { Icon: FileText, tone: "document", label: "Document" },
  spreadsheet: { Icon: FileSpreadsheet, tone: "sheet", label: "Spreadsheet" },
  unsupported: { Icon: Files, tone: "text", label: "File" },
} as const satisfies Record<KnowledgeDocumentKind, { Icon: typeof FileText; tone: string; label: string }>;

export function FileTypeIcon({
  kind,
  /** The format in the reader's words — "PDF", "DOCX". Names the mark. */
  label,
  size = "md",
  className,
}: {
  kind: KnowledgeDocumentKind;
  label?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const { Icon, tone, label: fallbackLabel } = presentation[kind];
  return (
    <span
      aria-label={label ?? fallbackLabel}
      className={cn("resource-icon", `resource-icon--${tone}`, size === "md" && "resource-icon--lg", className)}
      role="img"
    >
      <Icon aria-hidden="true" size={size === "md" ? 15 : 13} />
    </span>
  );
}
