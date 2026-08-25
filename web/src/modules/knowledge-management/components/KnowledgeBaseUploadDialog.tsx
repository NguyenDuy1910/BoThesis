"use client";

import {
  CheckCircle2,
  FileText,
  RefreshCw,
  ShieldAlert,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { getBothesisChatConfiguration } from "@/lib/api/config";
import { cn } from "@/lib/cn";
import {
  AdminApiError,
  adminRequest,
  uploadCollectionFile,
} from "@/modules/admin/api";
import {
  COLLECTION_UPLOAD_ACCEPT,
  collectionUploadFailure,
  type CollectionUploadQueueStatus,
  validateCollectionUploadFile,
} from "@/modules/knowledge-management/collection-upload";
import { formatBytes } from "@/modules/knowledge-management/presentation";
import type { CollectionUploadResponse } from "@/modules/knowledge-management/types";

interface QueuedUpload {
  id: string;
  idempotencyKey: string;
  file: File;
  progress: number;
  status: CollectionUploadQueueStatus;
  error?: string;
}

export function KnowledgeBaseUploadDialog({
  knowledgeBaseId,
  knowledgeBaseTitle,
  onClose,
  onUploaded,
}: {
  knowledgeBaseId: string;
  knowledgeBaseTitle: string;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
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
        return [{
          id: crypto.randomUUID(),
          idempotencyKey: crypto.randomUUID(),
          file,
          progress: 0,
          status: failure?.status ?? "queued",
          error: failure?.message,
        } satisfies QueuedUpload];
      });
      return [...current, ...additions];
    });
  }

  function updateUpload(id: string, changes: Partial<QueuedUpload>) {
    setQueue((current) => current.map((item) => (
      item.id === id ? { ...item, ...changes } : item
    )));
  }

  async function uploadOne(item: QueuedUpload) {
    updateUpload(item.id, { status: "uploading", progress: 0, error: undefined });
    try {
      const response = await uploadCollectionFile<CollectionUploadResponse>(
        knowledgeBaseId,
        item.file,
        {
          idempotencyKey: item.idempotencyKey,
          onProgress: (progress) => updateUpload(item.id, { progress }),
          onProcessing: () => updateUpload(item.id, { status: "processing", progress: 100 }),
        },
      );
      onUploaded();
      if (response.ingestion_status === "failed") {
        updateUpload(item.id, {
          status: "failed",
          progress: 100,
          error: "The file was stored, but indexing failed. Retry to process it again.",
        });
        return false;
      }
      updateUpload(item.id, { status: "ready", progress: 100, error: undefined });
      return true;
    } catch (cause) {
      const failure = collectionUploadFailure(
        cause instanceof AdminApiError ? cause.status : undefined,
        cause instanceof Error ? cause.message : "",
      );
      updateUpload(item.id, {
        status: failure.status,
        error: failure.message,
      });
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
        title: completed === 1 ? "File uploaded" : `${completed} files uploaded`,
        description: "Files were processed and indexed for search and chat.",
        variant: "success",
      });
    }
  }

  async function retry(item: QueuedUpload) {
    if (running) return;
    setRunning(true);
    const completed = await uploadOne(item);
    setRunning(false);
    if (completed) {
      toast({
        title: "File uploaded",
        description: `${item.file.name} is ready for search and chat.`,
        variant: "success",
      });
    }
  }

  async function requestAccess() {
    const configuration = getBothesisChatConfiguration();
    if (!configuration || requestingAccess) return;
    setRequestingAccess(true);
    try {
      await adminRequest("/access-requests", {
        method: "POST",
        body: JSON.stringify({
          requester_user_id: configuration.userId,
          collection_item_id: knowledgeBaseId,
          requested_role: "editor",
          reason: "Upload files to this knowledge base",
        }),
      });
      toast({
        title: "Access requested",
        description: "A collection editor can approve your upload access request.",
        variant: "success",
      });
    } catch (cause) {
      toast({
        title: "Access request could not be sent",
        description: cause instanceof Error ? cause.message : "Try again later.",
        variant: "error",
      });
    } finally {
      setRequestingAccess(false);
    }
  }

  return (
    <Dialog
      className="max-w-3xl"
      footer={(
        <>
          <Button onClick={onClose} variant="secondary">Close</Button>
          <Button
            disabled={!pendingCount}
            loading={running}
            onClick={() => void uploadQueued()}
          >
            Upload {pendingCount ? `${pendingCount} file${pendingCount === 1 ? "" : "s"}` : "files"}
          </Button>
        </>
      )}
      initialFocusRef={browseRef}
      onClose={onClose}
      open
      title="Upload files"
    >
      <p className="text-sm leading-6 text-[var(--text-muted)]">
        Upload files directly from your device to this knowledge base.
      </p>
      <div className="knowledge-upload-destination">
        <span>Destination</span>
        <strong>{knowledgeBaseTitle}</strong>
      </div>

      <div
        className={cn("knowledge-upload-dropzone", dragging && "is-dragging")}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
        }}
        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <UploadCloud aria-hidden="true" />
        <div>
          <p>Drag and drop files here</p>
          <span>or choose files from your device</span>
        </div>
        <Button
          ref={browseRef}
          onClick={() => inputRef.current?.click()}
          variant="secondary"
        >
          Browse files
        </Button>
        <input
          ref={inputRef}
          accept={COLLECTION_UPLOAD_ACCEPT.join(",")}
          className="sr-only"
          multiple
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
          tabIndex={-1}
          type="file"
        />
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        PDF, Office, text, data, and image files are supported. Maximum 100 MB per file.
        Files will be processed and indexed for search and chat.
      </p>

      {permissionDenied && (
        <div className="knowledge-upload-permission" role="alert">
          <ShieldAlert aria-hidden="true" />
          <div>
            <strong>You don’t have permission to upload files to this collection.</strong>
            <p>Request editor access from a collection owner.</p>
          </div>
          <Button loading={requestingAccess} onClick={() => void requestAccess()} variant="secondary">
            Request access
          </Button>
        </div>
      )}

      {queue.length > 0 && (
        <div aria-label="Upload queue" className="knowledge-upload-queue" role="region">
          <div className="knowledge-upload-queue__header">
            <h3>Upload queue</h3>
            <span>{queue.length} file{queue.length === 1 ? "" : "s"}</span>
          </div>
          <ul>
            {queue.map((item) => {
              const processing = item.status === "processing";
              const active = item.status === "uploading" || processing;
              const retryable = ["failed", "permission_denied", "unavailable"].includes(item.status);
              return (
                <li key={item.id}>
                  <span className="knowledge-upload-file__icon">
                    {item.status === "ready"
                      ? <CheckCircle2 aria-hidden="true" />
                      : item.error
                        ? <XCircle aria-hidden="true" />
                        : <FileText aria-hidden="true" />}
                  </span>
                  <div className="knowledge-upload-file__body">
                    <div className="knowledge-upload-file__title">
                      <strong title={item.file.name}>{item.file.name}</strong>
                      <span>{formatBytes(item.file.size)}</span>
                    </div>
                    <div aria-live="polite" className="knowledge-upload-file__status">
                      <StatusBadge status={uploadStatusLabel(item.status)} />
                      {item.error && <span>{item.error}</span>}
                    </div>
                    {active && (
                      <div
                        aria-label={processing
                          ? `${item.file.name} is being processed`
                          : `${item.file.name} ${item.progress}% uploaded`}
                        aria-valuemax={100}
                        aria-valuemin={0}
                        aria-valuenow={processing ? undefined : item.progress}
                        className="knowledge-upload-progress"
                        role="progressbar"
                      >
                        <span style={{ width: `${item.progress}%` }} />
                      </div>
                    )}
                  </div>
                  <div className="knowledge-upload-file__actions">
                    {retryable && (
                      <Button
                        aria-label={`Retry ${item.file.name}`}
                        disabled={running}
                        icon={<RefreshCw aria-hidden="true" />}
                        onClick={() => void retry(item)}
                        size="sm"
                        variant="ghost"
                      >
                        Retry
                      </Button>
                    )}
                    <Button
                      aria-label={`Remove ${item.file.name} from upload queue`}
                      disabled={active || running}
                      icon={<Trash2 aria-hidden="true" />}
                      onClick={() => setQueue((current) => current.filter((candidate) => candidate.id !== item.id))}
                      size="sm"
                      variant="ghost"
                    >
                      Remove
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Dialog>
  );
}

function fileIdentity(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function uploadStatusLabel(status: CollectionUploadQueueStatus) {
  const labels: Record<CollectionUploadQueueStatus, string> = {
    queued: "Queued",
    uploading: "Uploading",
    processing: "Processing",
    ready: "Ready",
    unsupported: "Unsupported",
    permission_denied: "Permission denied",
    unavailable: "Unavailable",
    failed: "Failed",
  };
  return labels[status];
}
