"use client";

import { BookOpen, Files, Globe, Search } from "lucide-react";

import { CollectionRow, DocumentRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  documentMeta,
  documentStatus,
} from "@/modules/knowledge/document-facts";
import type {
  WorkspaceKnowledgeCollection,
  WorkspaceKnowledgeDocument,
} from "@/modules/knowledge/workspace-repository";

import { DocumentBulkBar } from "./DocumentBulkBar";
import { FileTypeIcon } from "./FileTypeIcon";

const COLLECTION_ICON = {
  folder: BookOpen,
  upload: Files,
  web: Globe,
} as const;

interface DocumentsViewProps {
  collections: WorkspaceKnowledgeCollection[];
  documents: WorkspaceKnowledgeDocument[];
  /** Everything in the workspace, for the counts a filtered list cannot state. */
  totalDocumentCount: number;
  scope: string;
  search: string;
  /** True once a filter is narrowing the list beyond scope and search. */
  filtered: boolean;
  loading: boolean;
  selectedId: string;
  selection: string[];
  /** The list sits beside the viewer and drops its secondary columns. */
  compact: boolean;
  onOpenCollection: (name: string) => void;
  onOpenDocument: (document: WorkspaceKnowledgeDocument) => void;
  onToggleDocument: (id: string, checked: boolean) => void;
  onClearSelection: () => void;
  onReindexSelection: () => void;
  onExcludeSelection: () => void;
  onRemoveSelection: () => void;
  onClearFilters: () => void;
  onWidenScope: () => void;
  onConnectSource: () => void;
  onUpload: () => void;
}

export function DocumentsView({
  collections,
  documents,
  totalDocumentCount,
  scope,
  search,
  filtered,
  loading,
  selectedId,
  selection,
  compact,
  onOpenCollection,
  onOpenDocument,
  onToggleDocument,
  onClearSelection,
  onReindexSelection,
  onExcludeSelection,
  onRemoveSelection,
  onClearFilters,
  onWidenScope,
  onConnectSource,
  onUpload,
}: DocumentsViewProps) {
  if (loading) return <DocumentListSkeleton />;

  const browsing = !scope && !search && !filtered;
  const showCollections = browsing && !compact && collections.length > 0;
  const selectionSet = new Set(selection);
  const scopedCollection = collections.find((item) => item.name === scope);

  if (!documents.length && !showCollections) {
    return (
      <div className="knowledge-document-list">
        {search || filtered || scope ? (
          <SearchEmptyState
            onClearFilters={onClearFilters}
            onWidenScope={onWidenScope}
            scope={scope}
            scopeCount={scopedCollection?.documentCount}
            search={search}
            totalDocumentCount={totalDocumentCount}
          />
        ) : (
          <EmptyState
            action={
              <>
                <Button onClick={onConnectSource}>Connect a source</Button>
                <Button onClick={onUpload} variant="ghost">Upload files</Button>
              </>
            }
            description="This workspace can only answer from what you give it. Until a source is connected it will say it does not know."
            title="No knowledge yet"
          />
        )}
      </div>
    );
  }

  return (
    <div className="knowledge-document-list">
      {showCollections && (
        <section aria-labelledby="knowledge-collections-heading">
          <div className="knowledge-list-heading">
            <h2 className="knowledge-eyebrow" id="knowledge-collections-heading">Collections</h2>
            <span>{collections.length} collections</span>
          </div>
          <div className="knowledge-rows">
            {collections.map((collection) => (
              <CollectionRow
                count={collection.documentCount}
                icon={COLLECTION_ICON[collection.kind]}
                key={collection.name}
                name={collection.name}
                onOpen={() => onOpenCollection(collection.name)}
                restricted={collection.restricted}
                source={collection.source}
              />
            ))}
          </div>
        </section>
      )}

      {/* Beside the reader the heading is dropped — the scope control above
          already names the list — so the section labels itself instead of
          pointing at an element that is no longer rendered. */}
      <section
        aria-label={compact ? scope || "Documents" : undefined}
        aria-labelledby={compact ? undefined : "knowledge-documents-heading"}
      >
        {!compact && (
          <div className="knowledge-list-heading">
            <h2 className="knowledge-eyebrow" id="knowledge-documents-heading">
              {browsing ? "Recently updated" : scope || "Results"}
            </h2>
            <span>
              {browsing
                ? `${totalDocumentCount.toLocaleString()} in this workspace`
                : `${documents.length} ${documents.length === 1 ? "document" : "documents"}`}
            </span>
          </div>
        )}

        {selection.length > 0 && (
          <DocumentBulkBar
            count={selection.length}
            onClear={onClearSelection}
            onExclude={onExcludeSelection}
            onReindex={onReindexSelection}
            onRemove={onRemoveSelection}
          />
        )}

        <div className="knowledge-rows">
          {documents.map((document) => {
            const status = documentStatus(document);
            return (
              <DocumentRow
                checked={selectionSet.has(document.id)}
                icon={<FileTypeIcon kind={document.kind} label={document.fileTypeLabel} />}
                key={document.id}
                layout={compact ? "narrow" : "full"}
                meta={documentMeta(document, { scoped: compact || Boolean(scope), layout: compact ? "narrow" : "full" })}
                onCheckedChange={compact ? undefined : (checked) => onToggleDocument(document.id, checked)}
                onSelect={() => onOpenDocument(document)}
                selected={document.id === selectedId}
                status={status.label}
                statusTone={status.tone}
                title={document.title}
                updated={document.updatedLabel}
              />
            );
          })}
        </div>
      </section>
    </div>
  );
}

/**
 * A search that found nothing states what it covered before offering the one
 * action that widens it — otherwise the reader cannot tell whether the phrase
 * is absent from the collection or absent from the workspace.
 */
function SearchEmptyState({
  scope,
  scopeCount,
  search,
  totalDocumentCount,
  onWidenScope,
  onClearFilters,
}: {
  scope: string;
  scopeCount?: number;
  search: string;
  totalDocumentCount: number;
  onWidenScope: () => void;
  onClearFilters: () => void;
}) {
  const where = scope || "this workspace";
  return (
    <EmptyState
      action={
        scope
          ? <Button onClick={onWidenScope} variant="secondary">Search all {totalDocumentCount.toLocaleString()} documents</Button>
          : <Button onClick={onClearFilters} variant="secondary">Clear filters</Button>
      }
      description={
        scope && scopeCount
          ? `This search covered ${scopeCount.toLocaleString()} documents in one collection.`
          : "No document in the current filters matches."
      }
      icon={<Search size={20} />}
      title={search ? `Nothing in ${where} matches “${search}”` : `Nothing in ${where} matches these filters`}
    />
  );
}

/**
 * Row height is reserved so the list does not jump when results arrive, and
 * the toolbar above stays live throughout — only the rows are waiting.
 */
function DocumentListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-live="polite" className="knowledge-document-list">
      <span className="sr-only">Loading documents</span>
      <div className="knowledge-rows">
        {Array.from({ length: rows }).map((_, index) => (
          <div className="knowledge-row-skeleton" key={index}>
            <Skeleton className="h-7 w-7 rounded-[var(--radius-xs)]" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <Skeleton className="h-3 w-[38%]" />
              <Skeleton className="h-2.5 w-[22%]" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
