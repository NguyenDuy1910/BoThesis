import { LockKeyhole } from "lucide-react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { cn } from "@/lib/cn";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

import { FileTypeIcon } from "./FileTypeIcon";

export function WorkspaceDocumentRow({
  document,
  selected,
  onSelect,
}: {
  document: WorkspaceKnowledgeDocument;
  selected: boolean;
  onSelect: () => void;
}) {
  const status = document.state === "indexed" ? "ready" : document.state === "failed" ? "failed" : "indexing";
  return (
    <button
      aria-current={selected ? "true" : undefined}
      className={cn(
        "flex w-full items-center gap-3 border-b border-[var(--border-subtle)] px-4 py-3 text-left transition-colors",
        "hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
        selected && "bg-[var(--surface-selected)]",
      )}
      onClick={onSelect}
      type="button"
    >
      <FileTypeIcon kind={document.kind} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[length:var(--text-size-ui)] font-medium text-[var(--text-primary)]">{document.title}</span>
        <span className="mt-0.5 flex items-center gap-1 truncate text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
          {document.state === "restricted" && <LockKeyhole aria-hidden="true" size={11} />}
          {document.collection} · {document.pagesLabel} · {document.updatedLabel}
        </span>
      </span>
      <StatusBadge className="shrink-0" status={status} />
    </button>
  );
}
