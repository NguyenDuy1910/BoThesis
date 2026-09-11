"use client";

import {
  CheckCircle2,
  FileText,
  RotateCw,
  ShieldAlert,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import { getChatConfiguration } from "@/lib/api/config";
import { cn } from "@/lib/cn";
import { AdminApiError, adminRequest, uploadCollectionFile } from "@/modules/admin/api";
import type { CollectionUploadResponse } from "@/modules/admin/collections";
import {
  COLLECTION_UPLOAD_ACCEPT,
  collectionUploadFailure,
  type CollectionUploadQueueStatus,
  validateCollectionUploadFile,
} from "@/modules/admin/collection-upload";
import { errorMessage, formatBytes } from "@/modules/admin/format";

interface QueuedUpload {
  id: string;
  idempotencyKey: string;
  file: File;
  progress: number;
  status: CollectionUploadQueueStatus;
  error?: string;
}

const statusTone: Record<
  CollectionUploadQueueStatus,
  { label: string; tone: "neutral" | "info" | "success" | "danger" | "warning" }
> = {
  queued: { label: "Ready to upload", tone: "neutral" },
  uploading: { label: "Uploading", tone: "info" },
  processing: { label: "Indexing", tone: "info" },
  ready: { label: "Searchable", tone: "success" },
  unsupported: { label: "Unsupported type", tone: "warning" },
  permission_denied: { label: "No permission", tone: "danger" },
  unavailable: { label: "Unavailable", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
};

function fileIdentity(file: File) {
  return `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`;
}

export function CollectionUploadDialog({
  collectionId,
  collectionTitle,
  onClose,
  onUploaded,
}: {
  collectionId: string;
  collectionTitle: string;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const browseRef = useRef<HTMLButtonElement | null>(null);
  const [queue, setQueue] = useState<QueuedUpload[]>([]);
  const [dragging, setDragging] = useState(false);
  const [running, setRunning] = useState(false);
  const [requestingAccess, setRequestingAccess] = useState(false);

  const permissionDenied = queue.some((item) => item.status === "permission_denied");
  const pendingCount = queue.filter((item) => item.status === "queued").length;

  function addFiles(files: FileList | File[]) {
    const candidates = Array.from(files);
    setQueue((current) => {
      const known = new Set(current.map((item) => fileIdentity(item.file)));
      const additions = candidates.flatMap((file) => {
        const identity = fileIdentity(file);
        if (known.has(identity)) return [];
        known.add(identity);
        const failure = validateCollectionUploadFile(file);
        return [
          {
            id: crypto.randomUUID(),
            idempotencyKey: crypto.randomUUID(),
            file,
            progress: 0,
            status: failure?.status ?? "queued",
            error: failure?.message,
          } satisfies QueuedUpload,
        ];
      });
      return [...current, ...additions];
    });
  }

  function update(id: string, changes: Partial<QueuedUpload>) {
    setQueue((current) =>
      current.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    );
  }

  async function uploadOne(item: QueuedUpload) {
    update(item.id, { status: "uploading", progress: 0, error: undefined });
    try {
      const response = await uploadCollectionFile<CollectionUploadResponse>(
        collectionId,
        item.file,
        {
          idempotencyKey: item.idempotencyKey,
          onProgress: (progress) => update(item.id, { progress }),
          onProcessing: () => update(item.id, { status: "processing", progress: 100 }),
        },
      );
      onUploaded();
      if (response.ingestion_status === "failed") {
        update(item.id, {
          status: "failed",
          progress: 100,
          error: "Stored, but indexing failed. Try again.",
        });
        return false;
      }
      update(item.id, { status: "ready", progress: 100, error: undefined });
      return true;
    } catch (cause) {
      const failure = collectionUploadFailure(
        cause instanceof AdminApiError ? cause.status : undefined,
        cause instanceof Error ? cause.message : "",
      );
      update(item.id, { status: failure.status, error: failure.message });
      return false;
    }
  }

  async function uploadQueued() {
    const pending = queue.filter((item) => item.status === "queued");
    if (!pending.length || running) return;
    setRunning(true);
    let completed = 0;
    for (const item of pending) {
      if (await uploadOne(item)) completed += 1;
    }
    setRunning(false);
    if (completed) {
      toast({
        title:
          completed === 1 ? "File is searchable" : `${completed} files are searchable`,
        description: `Added to ${collectionTitle}.`,
        variant: "success",
      });
    }
  }

  async function requestAccess() {
    const configuration = getChatConfiguration();
    if (!configuration || requestingAccess) return;
    setRequestingAccess(true);
    try {
      await adminRequest("/access-requests", {
        method: "POST",
        body: JSON.stringify({
          requester_user_id: configuration.userId,
          collection_item_id: collectionId,
          requested_role: "editor",
          reason: `Upload files to ${collectionTitle}`,
        }),
      });
      toast({
        title: "Access requested",
        description: "An owner of this collection can approve it.",
        variant: "success",
      });
    } catch (cause) {
      toast({
        title: "Request could not be sent",
        description: errorMessage(cause),
        variant: "error",
      });
    } finally {
      setRequestingAccess(false);
    }
  }

  return (
    <Dialog
      className="max-w-2xl"
      footer={
        <>
          <Button onClick={onClose} variant="secondary">
            {queue.some((item) => item.status === "ready") ? "Done" : "Cancel"}
          </Button>
          <Button
            disabled={!pendingCount}
            loading={running}
            onClick={() => void uploadQueued()}
          >
            {pendingCount
              ? `Upload ${pendingCount} file${pendingCount === 1 ? "" : "s"}`
              : "Upload files"}
          </Button>
        </>
      }
      initialFocusRef={browseRef}
      onClose={onClose}
      open
      title={`Upload to ${collectionTitle}`}
    >
      <div
        className={cn(
          "flex flex-col items-center gap-2.5 rounded-[var(--adm-r-lg)] px-6 py-8 text-center transition-colors",
          "bg-[var(--adm-inset)] shadow-[inset_0_0_0_1.5px_var(--adm-hairline-strong)]",
          dragging &&
            "bg-[var(--brand-accent-soft)] shadow-[inset_0_0_0_1.5px_var(--brand-accent)]",
        )}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setDragging(false);
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <UploadCloud
          aria-hidden="true"
          className="h-7 w-7 text-[var(--text-muted)]"
        />
        <p className="text-[0.875rem] font-medium text-[var(--text)]">
          Drag files or folders here
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button
            onClick={() => inputRef.current?.click()}
            ref={browseRef}
            size="sm"
            variant="secondary"
          >
            Choose files
          </Button>
          <Button
            onClick={() => folderInputRef.current?.click()}
            size="sm"
            variant="secondary"
          >
            Choose folder
          </Button>
        </div>
        <input
          accept={COLLECTION_UPLOAD_ACCEPT.join(",")}
          className="sr-only"
          multiple
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
          ref={inputRef}
          tabIndex={-1}
          type="file"
        />
        <input
          accept={COLLECTION_UPLOAD_ACCEPT.join(",")}
          className="sr-only"
          multiple
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
          ref={(element) => {
            folderInputRef.current = element;
            if (element) element.setAttribute("webkitdirectory", "");
          }}
          tabIndex={-1}
          type="file"
        />
        <p className="mt-1 text-[0.75rem] leading-4 text-[var(--text-muted)]">
          PDF, Office, text, data and image files. Up to 100 MB each; unsupported files are skipped.
        </p>
      </div>

      {permissionDenied && (
        <div
          className="mt-4 flex items-start gap-2.5 rounded-[var(--adm-r-sm)] bg-[var(--danger-soft)] px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--danger-border)]"
          role="alert"
        >
          <ShieldAlert
            aria-hidden="true"
            className="mt-px h-4 w-4 shrink-0 text-[var(--danger)]"
          />
          <div className="min-w-0 flex-1">
            <p className="text-[0.8125rem] font-medium text-[var(--danger-text)]">
              You cannot upload to this collection
            </p>
            <p className="mt-0.5 text-[0.75rem] leading-4 text-[var(--danger-text)]">
              Ask an owner for editor access, or request it here.
            </p>
          </div>
          <Button
            loading={requestingAccess}
            onClick={() => void requestAccess()}
            size="sm"
            variant="secondary"
          >
            Request access
          </Button>
        </div>
      )}

      {queue.length > 0 && (
        <ul aria-label="Files to upload" className="mt-4 space-y-1.5">
          {queue.map((item) => {
            const active = item.status === "uploading" || item.status === "processing";
            const retryable = ["failed", "permission_denied", "unavailable"].includes(
              item.status,
            );
            const tone = statusTone[item.status];
            return (
              <li
                className="flex items-center gap-2.5 rounded-[var(--adm-r-sm)] bg-[var(--adm-inset)] px-3 py-2 shadow-[inset_0_0_0_1px_var(--adm-hairline)]"
                key={item.id}
              >
                <span aria-hidden="true" className="shrink-0">
                  {item.status === "ready" ? (
                    <CheckCircle2 className="h-4 w-4 text-[var(--success)]" />
                  ) : item.error ? (
                    <XCircle className="h-4 w-4 text-[var(--danger)]" />
                  ) : (
                    <FileText className="h-4 w-4 text-[var(--text-muted)]" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span
                      className="min-w-0 truncate text-[0.8125rem] font-medium text-[var(--text)]"
                      title={item.file.name}
                    >
                      {item.file.name}
                    </span>
                    <span className="shrink-0 text-[0.6875rem] tabular-nums text-[var(--text-muted)]">
                      {formatBytes(item.file.size)}
                    </span>
                  </div>
                  {active ? (
                    <div
                      aria-label={`${item.file.name} ${item.progress}% uploaded`}
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={
                        item.status === "processing" ? undefined : item.progress
                      }
                      className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--adm-hairline-strong)]"
                      role="progressbar"
                    >
                      <span
                        className="block h-full rounded-full bg-[var(--brand-accent)] transition-[width] duration-[var(--adm-base)]"
                        style={{ width: `${item.progress}%` }}
                      />
                    </div>
                  ) : (
                    item.error && (
                      <p className="mt-0.5 text-[0.75rem] leading-4 text-[var(--danger-text)]">
                        {item.error}
                      </p>
                    )
                  )}
                </div>
                <Badge tone={tone.tone}>{tone.label}</Badge>
                {retryable && (
                  <Button
                    aria-label={`Retry ${item.file.name}`}
                    disabled={running}
                    icon={<RotateCw aria-hidden="true" className="h-3.5 w-3.5" />}
                    iconOnly
                    onClick={() => void uploadOne(item)}
                    size="sm"
                    variant="ghost"
                  />
                )}
                <Button
                  aria-label={`Remove ${item.file.name}`}
                  disabled={active || running}
                  icon={<X aria-hidden="true" className="h-3.5 w-3.5" />}
                  iconOnly
                  onClick={() =>
                    setQueue((current) =>
                      current.filter((candidate) => candidate.id !== item.id),
                    )
                  }
                  size="sm"
                  variant="ghost"
                />
              </li>
            );
          })}
        </ul>
      )}
    </Dialog>
  );
}
