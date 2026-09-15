"use client";

import { ArrowLeft, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { CommandBar, FilterTrigger } from "@/components/layout/CommandBar";
import { SplitView } from "@/components/layout/SplitView";
import { DocumentRow } from "@/components/patterns";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useRouteState } from "@/lib/hooks/useRouteState";
import { DocumentViewer } from "@/modules/knowledge/components/DocumentViewer";
import { FileTypeIcon } from "@/modules/knowledge/components/FileTypeIcon";
import { libraryActions, useLibrary } from "./queries";

/**
 * The documents that belong to this person rather than to the workspace.
 *
 * They live in the private Collection every member is given, so what is shown
 * here is exactly what the knowledge service holds for them — uploads, and
 * whatever a conversation saved on their behalf.
 */
export function LibraryScreen() {
  const router = useRouter();
  const query = useLibrary();
  const [selectedId, setSelectedId] = useRouteState("document");
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upload = useRef<HTMLInputElement>(null);

  const documents = query.data?.documents ?? [];
  const collectionId = query.data?.collectionId ?? null;
  const selected = documents.find((item) => item.id === selectedId);
  const rows = documents.filter((item) =>
    (!type || item.kind === type) && item.title.toLowerCase().includes(search.toLowerCase()),
  );

  const list = (
    <div className="px-[var(--page-gutter)] pb-5">
      <h2 className="document-heading">{query.data?.collectionTitle ?? "My documents"}</h2>
      {query.loading ? (
        <p role="status">Loading your documents…</p>
      ) : !rows.length ? (
        <EmptyState
          action={
            <Button disabled={!collectionId} onClick={() => upload.current?.click()} variant="ghost">
              Upload a file
            </Button>
          }
          description={
            search || type
              ? "Try a different search or clear the filters."
              : "Upload a document, or save one from a conversation."
          }
          title={search || type ? "No results" : "Your library is empty"}
        />
      ) : (
        rows.map((item) => (
          <DocumentRow
            icon={<FileTypeIcon kind={item.kind} />}
            key={item.id}
            layout={selected ? "narrow" : "full"}
            meta={item.source}
            onSelect={() => { setSelectedId(item.id); setExpanded(false); }}
            selected={item.id === selectedId}
            title={item.title}
            updated={item.updatedLabel}
          />
        ))
      )}
    </div>
  );

  return (
    <section aria-label="Personal library" className="document-workspace">
      <div className="px-[var(--page-gutter)] pt-4">
        <Button icon={<ArrowLeft size={16} />} onClick={() => router.push("/app")} variant="ghost">
          Back to chat
        </Button>
      </div>
      <CommandBar
        action={
          <Button
            disabled={!collectionId}
            icon={<Upload size={16} />}
            loading={busy}
            onClick={() => upload.current?.click()}
          >
            Upload
          </Button>
        }
        count={`${rows.length} documents`}
        filters={
          <FilterTrigger
            label="Filter by type"
            onChange={setType}
            options={[
              { value: "", label: "All types" },
              { value: "pdf", label: "PDF" },
              { value: "document", label: "Documents" },
              { value: "spreadsheet", label: "Spreadsheets" },
            ]}
            value={type}
          />
        }
        search={{ value: search, onChange: setSearch, placeholder: "Search your documents…", label: "Search library" }}
      />
      {error || query.error ? (
        <div className="px-[var(--page-gutter)]">
          <ErrorState
            description={error ?? query.error ?? ""}
            onAction={() => { setError(null); query.reload(); }}
          />
        </div>
      ) : null}
      <SplitView
        detail={selected ? (
          <DocumentViewer
            document={selected}
            expanded={expanded}
            onClose={() => setSelectedId("")}
            onExpand={() => setExpanded((value) => !value)}
          />
        ) : null}
        list={list}
        mode={selected ? (expanded ? "detail" : "split") : "list"}
      />
      <input
        aria-label="Upload a document"
        className="hidden"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file || !collectionId) return;
          setBusy(true);
          setError(null);
          try {
            await libraryActions.upload(file, collectionId);
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "Upload failed.");
          } finally {
            setBusy(false);
            event.target.value = "";
          }
        }}
        ref={upload}
        type="file"
      />
    </section>
  );
}
