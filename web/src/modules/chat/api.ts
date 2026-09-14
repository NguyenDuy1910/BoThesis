import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import { mockApi, previewMode } from "@/mocks/bothesis-api.mock";
import { StreamEventDeduplicator } from "./stream-deduplicator";
import type {
  AgentHistoryMessage,
  ConversationDocument,
  MessageItem,
  ResponseStreamEvent,
} from "./types";
import { DOCUMENT_CITATION_TYPE } from "./types";

const uploadIdempotencyKeys = new WeakMap<File, string>();

export class ChatConfigurationError extends Error {
  constructor() {
    super(
      "Chat is unavailable. Sign in, or configure the explicit local development identity."
    );
  }
}

export async function streamAgentResponse(
  message: string,
  options: {
    conversationId?: string | null;
    history: AgentHistoryMessage[];
    attachmentIds?: string[];
    collectionItemIds?: string[];
    signal: AbortSignal;
    onEvent: (event: ResponseStreamEvent) => void;
  }
): Promise<void> {
  if (previewMode) {
    await streamPreviewResponse(message, options);
    return;
  }
  const configuration = getApiConfiguration();
  if (!configuration) throw new ChatConfigurationError();

  const response = await fetch(`${configuration.apiUrl}/api/v1/agent/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...requestIdentityHeaders(configuration),
    },
    signal: options.signal,
    body: JSON.stringify({
      message,
      conversation_id: options.conversationId ?? null,
      history: options.history,
      attachment_ids: options.attachmentIds ?? [],
      collection_item_ids: options.collectionItemIds ?? [],
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
  mode: "presigned";
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
  status: "pending" | "processing" | "ready" | "failed" | "unsupported";
  upload_status: "pending" | "available" | "failed" | null;
}

export async function uploadConversationDocument(
  file: File,
  options: {
    signal: AbortSignal;
    onProgress?: (status: "starting" | "uploading" | "validating") => void;
  },
): Promise<ConversationDocument> {
  if (previewMode) {
    if (file.size > 25 * 1024 * 1024) throw new Error("Choose a file smaller than 25 MB.");
    options.onProgress?.("starting");
    await previewDelay(100, options.signal);
    options.onProgress?.("uploading");
    await previewDelay(180, options.signal);
    options.onProgress?.("validating");
    await previewDelay(120, options.signal);
    return {
      id: crypto.randomUUID(),
      fileName: file.name,
      contentType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      mode: file.size <= 20 * 1024 * 1024 ? "direct" : "indexed",
      status: "available",
    };
  }
  const configuration = getApiConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  options.onProgress?.("starting");
  const identityHeaders = requestIdentityHeaders(configuration);
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
  const uploadResponse = await uploadToTarget(
    started.target,
    file,
    options.signal,
  );
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
  if (previewMode) return;
  const configuration = getApiConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
      headers: requestIdentityHeaders(configuration),
    },
  );
  if (!response.ok && response.status !== 404) {
    throw await responseError(response, "Could not remove the document.");
  }
}

export interface ArtifactRevision {
  revision: number;
  summary: string | null;
  size_bytes: number;
  created_at: string | null;
  download_url: string | null;
}

export interface ArtifactDetail {
  id: string;
  title: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  revision: number;
  revision_count: number;
  conversation_id: string | null;
  source_document_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  download_url: string | null;
  revisions: ArtifactRevision[];
}

export interface ArtifactContent {
  artifact_id: string;
  revision: number;
  mime_type: string;
  content: string;
  truncated: boolean;
}

/** A Collection the caller may read — the publish destination picker's options. */
export interface Collection {
  id: string;
  title: string;
  parent_item_id: string | null;
}

export interface ArtifactPublishResult {
  artifact_id: string;
  revision: number;
  item_id: string;
  collection_id: string;
  title: string;
  status: string;
  created: boolean;
}

/** Download URLs are short-lived, so the detail is fetched when it is acted on. */
export async function getArtifact(
  artifactId: string,
  signal?: AbortSignal,
): Promise<ArtifactDetail> {
  return artifactRequest<ArtifactDetail>(
    `/api/v1/artifacts/${encodeURIComponent(artifactId)}`,
    { signal },
    "Could not load the document.",
  );
}

export async function getArtifactContent(
  artifactId: string,
  revision: number,
  signal?: AbortSignal,
): Promise<ArtifactContent> {
  return artifactRequest<ArtifactContent>(
    `/api/v1/artifacts/${encodeURIComponent(artifactId)}/revisions/${revision}/content`,
    { signal },
    "Could not load the document content.",
  );
}

/**
 * The Collections the caller may publish an artifact into.
 *
 * Reuses the same listing the chat knowledge-scope picker uses — there is no
 * separate "template library" kind of Collection to enumerate; any Collection
 * the caller can write to is a valid publish destination.
 */
export async function listCollections(signal?: AbortSignal): Promise<Collection[]> {
  if (previewMode) {
    const collections = await mockApi.library.collections();
    if (signal?.aborted) return [];
    return collections.map((collection) => ({
      id: collection.id,
      title: collection.name,
      parent_item_id: null,
    }));
  }
  const result = await artifactRequest<{ items: Collection[] }>(
    "/api/v1/agent/collections",
    { signal },
    "Could not load your collections.",
  );
  return result.items;
}

async function streamPreviewResponse(
  message: string,
  options: {
    signal: AbortSignal;
    onEvent: (event: ResponseStreamEvent) => void;
    attachmentIds?: string[];
    collectionItemIds?: string[];
  },
) {
  const responseId = crypto.randomUUID();
  const itemId = crypto.randomUUID();
  const answer = previewAnswer(message, Boolean(options.attachmentIds?.length));
  const citation = {
    type: DOCUMENT_CITATION_TYPE,
    start_index: Math.max(0, answer.length - 1),
    end_index: answer.length,
    citation: {
      id: "travel-policy-citation",
      reference: "workspace:travel-policy",
      number: 1,
      item_id: "travel-policy",
      chunk_id: "travel-policy:section-3",
      title: "Travel reimbursement policy.pdf",
      section: "Section 3 — Reimbursement",
      page_start: 4,
      page_end: 5,
      internal_url: "/admin/knowledge?document=travel-policy",
      source: { provider: "Google Drive", external_id: "travel-policy" },
    },
  };
  let sequence = 0;
  const send = (event: ResponseStreamEvent) => {
    if (!options.signal.aborted) options.onEvent({ ...event, sequence_number: sequence++ });
  };
  send({ type: "tool_started", call_id: "preview-search", tool_name: "Search workspace knowledge" });
  await previewDelay(120, options.signal);
  if (options.signal.aborted) return;
  send({ type: "tool_progress", call_id: "preview-search", tool_name: "Search workspace knowledge", data: { status: "Searching permitted sources" } });
  await previewDelay(140, options.signal);
  send({ type: "tool_completed", call_id: "preview-search", tool_name: "Search workspace knowledge", status: "completed", result_count: 3, duration_ms: 260 });
  send({ type: "response.created", response: { id: responseId, status: "in_progress", output: [] } });
  const opening: MessageItem = { id: itemId, type: "message", role: "assistant", status: "in_progress", content: [] };
  send({ type: "response.output_item.added", output_index: 0, item: opening });
  send({ type: "response.content_part.added", item_id: itemId, output_index: 0, content_index: 0, part: { type: "output_text", text: "", annotations: [] } });
  for (const chunk of answer.match(/.{1,34}(?:\s|$)/g) ?? [answer]) {
    await previewDelay(24, options.signal);
    if (options.signal.aborted) return;
    send({ type: "response.output_text.delta", item_id: itemId, output_index: 0, content_index: 0, delta: chunk });
  }
  send({ type: "response.output_text.annotation.added", item_id: itemId, output_index: 0, content_index: 0, annotation_index: 0, annotation: citation });
  send({ type: "response.output_text.done", item_id: itemId, output_index: 0, content_index: 0, text: answer });
  const finalPart = { type: "output_text" as const, text: answer, annotations: [citation] };
  const finalItem: MessageItem = { ...opening, status: "completed", phase: "final_answer", content: [finalPart] };
  send({ type: "response.content_part.done", item_id: itemId, output_index: 0, content_index: 0, part: finalPart });
  send({ type: "response.output_item.done", output_index: 0, item: finalItem });
  send({ type: "response.completed", response: { id: responseId, status: "completed", output: [finalItem] } });
}

function previewAnswer(message: string, hasAttachment: boolean) {
  const prompt = message.toLowerCase();
  if (hasAttachment) {
    return "I reviewed the attached file in this preview. Its main points are organized clearly, but any policy decision should be checked against the authoritative workspace source. The workspace travel policy requires supporting receipts and manager review for late claims.";
  }
  if (prompt.includes("graduat") || prompt.includes("thesis")) {
    return "The graduation workflow starts with confirming programme requirements, resolving outstanding credits, and submitting the signed thesis approval before the department deadline. I would verify the intake-specific date in the current academic calendar before you act.";
  }
  if (prompt.includes("travel") || prompt.includes("reimburse") || prompt.includes("receipt")) {
    return "For approved university travel, reasonable transport, accommodation, and meal costs may be reimbursed. Submit the claim with supporting receipts within 30 calendar days after the trip; later claims require manager approval.";
  }
  return "I found relevant guidance in the permitted workspace knowledge. The safest next step is to confirm the applicable policy, owner, and effective date before acting. I can narrow this answer if you share the process or document you are working with.";
}

function previewDelay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

export async function publishArtifact(
  artifactId: string,
  collectionId: string,
): Promise<ArtifactPublishResult> {
  return artifactRequest<ArtifactPublishResult>(
    `/api/v1/artifacts/${encodeURIComponent(artifactId)}/publish`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection_id: collectionId }),
    },
    "Could not publish the document to the Knowledge Base.",
  );
}

async function artifactRequest<T>(
  path: string,
  init: RequestInit,
  fallback: string,
): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  const response = await fetch(`${configuration.apiUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...(init.headers ?? {}), ...requestIdentityHeaders(configuration) },
  });
  if (!response.ok) throw await responseError(response, fallback);
  return await response.json() as T;
}

async function uploadToTarget(
  target: DocumentUploadTarget,
  file: File,
  signal: AbortSignal,
) {
  return fetch(target.url, {
    method: target.method,
    headers: target.headers,
    body: file,
    signal,
  });
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
