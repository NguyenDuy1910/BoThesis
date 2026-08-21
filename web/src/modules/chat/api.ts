import {
  getBothesisChatConfiguration,
  type BothesisChatConfiguration,
} from "@/lib/api/config";
import { StreamEventDeduplicator } from "./stream-deduplicator";
import type {
  AgentHistoryMessage,
  ConversationDocument,
  ResponseStreamEvent,
} from "./types";

const uploadIdempotencyKeys = new WeakMap<File, string>();

export class ChatConfigurationError extends Error {
  constructor() {
    super(
      "Chat is not configured. Set NEXT_PUBLIC_BOTHESIS_API_URL, NEXT_PUBLIC_BOTHESIS_TENANT_ID, and NEXT_PUBLIC_BOTHESIS_USER_ID."
    );
  }
}

export async function streamAgentResponse(
  message: string,
  options: {
    conversationId?: string | null;
    history: AgentHistoryMessage[];
    documentIds?: string[];
    signal: AbortSignal;
    onEvent: (event: ResponseStreamEvent) => void;
  }
): Promise<void> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();

  const response = await fetch(`${configuration.apiUrl}/api/v1/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...developmentIdentityHeaders(configuration),
    },
    signal: options.signal,
    body: JSON.stringify({
      message,
      conversation_id: options.conversationId ?? null,
      history: options.history,
      document_ids: options.documentIds ?? [],
    }),
  });
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Chat request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const deduplicator = new StreamEventDeduplicator();

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop() ?? "";

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        const event = JSON.parse(payload) as ResponseStreamEvent;
        if (!deduplicator.shouldAccept(event)) continue;
        options.onEvent(event);
      } catch {
        throw new Error("Received an invalid agent stream event.");
      }
    }
    if (done) break;
  }
}

interface DocumentUploadStartResponse {
  upload_required: boolean;
  target?: DocumentUploadTarget | null;
  document: DocumentMetadataResponse;
}

interface DocumentUploadTarget {
  mode: "presigned" | "api";
  url: string;
  method: string;
  headers: Record<string, string>;
  expires_at: string;
}

interface DocumentMetadataResponse {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  upload_status: "not_applicable" | "pending" | "available" | "failed";
  indexing_status: string;
}

export async function uploadConversationDocument(
  file: File,
  options: {
    signal: AbortSignal;
    onProgress?: (status: "starting" | "uploading" | "validating") => void;
  },
): Promise<ConversationDocument> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  options.onProgress?.("starting");
  const identityHeaders = developmentIdentityHeaders(configuration);
  const startResponse = await fetch(`${configuration.apiUrl}/api/v1/documents/uploads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": uploadIdempotencyKey(file),
      ...identityHeaders,
    },
    signal: options.signal,
    body: JSON.stringify({
      file_name: file.name,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
    }),
  });
  if (!startResponse.ok) {
    throw await responseError(startResponse, "Could not start document upload.");
  }
  const started = await startResponse.json() as DocumentUploadStartResponse;
  if (!started.upload_required) return documentFromResponse(started.document);
  if (!started.target) {
    throw new Error("Document upload did not return a storage destination.");
  }

  options.onProgress?.("uploading");
  let uploadResponse: Response;
  try {
    uploadResponse = await uploadToTarget(
      started.target,
      started.document.id,
      file,
      configuration,
      identityHeaders,
      options.signal,
    );
  } catch (cause) {
    if (options.signal.aborted || started.target.mode !== "presigned") throw cause;
    uploadResponse = await uploadToApiFallback(
      started.document.id,
      file,
      configuration,
      identityHeaders,
      options.signal,
    );
  }
  if (!uploadResponse.ok && started.target.mode === "presigned") {
    uploadResponse = await uploadToApiFallback(
      started.document.id,
      file,
      configuration,
      identityHeaders,
      options.signal,
    );
  }
  if (!uploadResponse.ok) {
    throw await responseError(uploadResponse, "Document storage rejected the upload.");
  }

  options.onProgress?.("validating");
  const completeResponse = await fetch(
    `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(started.document.id)}/complete`,
    {
      method: "POST",
      headers: identityHeaders,
      signal: options.signal,
    },
  );
  if (!completeResponse.ok) {
    throw await responseError(completeResponse, "Could not validate the uploaded document.");
  }
  return documentFromResponse(await completeResponse.json() as DocumentMetadataResponse);
}

export async function releaseConversationDocument(documentId: string): Promise<void> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
      headers: developmentIdentityHeaders(configuration),
    },
  );
  if (!response.ok && response.status !== 404) {
    throw await responseError(response, "Could not remove the document.");
  }
}

async function uploadToTarget(
  target: DocumentUploadTarget,
  documentId: string,
  file: File,
  configuration: BothesisChatConfiguration,
  identityHeaders: Record<string, string>,
  signal: AbortSignal,
) {
  if (target.mode === "api") {
    return uploadToApiFallback(
      documentId,
      file,
      configuration,
      identityHeaders,
      signal,
    );
  }
  return fetch(target.url, {
    method: target.method,
    headers: target.headers,
    body: file,
    signal,
  });
}

function uploadToApiFallback(
  documentId: string,
  file: File,
  configuration: BothesisChatConfiguration,
  identityHeaders: Record<string, string>,
  signal: AbortSignal,
) {
  return fetch(
    `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}/content`,
    {
      method: "PUT",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        ...identityHeaders,
      },
      body: file,
      signal,
    },
  );
}

function developmentIdentityHeaders(configuration: {
  userId: string;
  tenantId: string;
}): Record<string, string> {
  return {
    "X-Bothesis-User-Id": configuration.userId,
    "X-Bothesis-Tenant-Id": configuration.tenantId,
  };
}

function uploadIdempotencyKey(file: File): string {
  const existing = uploadIdempotencyKeys.get(file);
  if (existing) return existing;
  const created = crypto.randomUUID();
  uploadIdempotencyKeys.set(file, created);
  return created;
}

function documentFromResponse(value: DocumentMetadataResponse): ConversationDocument {
  const directTypes = new Set([
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
  ]);
  const direct = value.size_bytes <= 20 * 1024 * 1024 && (
    directTypes.has(value.content_type)
  );
  return {
    id: value.id,
    fileName: value.file_name,
    contentType: value.content_type,
    sizeBytes: value.size_bytes,
    mode: direct ? "direct" : "indexed",
    status: value.upload_status === "available" ? "available" : "failed",
  };
}

async function responseError(response: Response, fallback: string) {
  try {
    const value = await response.json() as { detail?: unknown };
    if (typeof value.detail === "string" && value.detail) return new Error(value.detail);
  } catch {
    // The caller still receives a stable fallback for non-JSON errors.
  }
  return new Error(fallback);
}
