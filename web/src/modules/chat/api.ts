import { getBothesisChatConfiguration } from "@/lib/api/config";
import { StreamEventDeduplicator } from "./stream-deduplicator";
import type {
  AgentHistoryMessage,
  AgentStreamEvent,
  ConversationAttachment,
} from "./types";

export class ChatConfigurationError extends Error {
  constructor() {
    super(
      "Chat is not configured. Set NEXT_PUBLIC_BOTHESIS_API_URL, NEXT_PUBLIC_BOTHESIS_TENANT_ID, NEXT_PUBLIC_BOTHESIS_USER_ID, and NEXT_PUBLIC_BOTHESIS_ROLES."
    );
  }
}

export async function streamAgentResponse(
  message: string,
  options: {
    conversationId?: string | null;
    history: AgentHistoryMessage[];
    attachmentIds?: string[];
    signal: AbortSignal;
    onEvent: (event: AgentStreamEvent) => void;
  }
): Promise<void> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();

  const response = await fetch(`${configuration.apiUrl}/api/v1/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({
      message,
      tenant_id: configuration.tenantId,
      user_id: configuration.userId,
      roles: configuration.roles,
      conversation_id: options.conversationId ?? null,
      history: options.history,
      attachment_ids: options.attachmentIds ?? [],
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
        const event = JSON.parse(payload) as AgentStreamEvent;
        if (!deduplicator.shouldAccept(event)) continue;
        options.onEvent(event);
      } catch {
        throw new Error("Received an invalid agent stream event.");
      }
    }
    if (done) break;
  }
}

interface AttachmentUploadStartResponse {
  upload_id?: string | null;
  upload_required: boolean;
  upload?: {
    url: string;
    method: string;
    headers: Record<string, string>;
    expires_at: string;
  } | null;
  attachment?: AttachmentMetadataResponse | null;
}

interface AttachmentMetadataResponse {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  mode: ConversationAttachment["mode"];
  status: ConversationAttachment["status"];
}

export async function uploadConversationAttachment(
  file: File,
  conversationId: string,
  options: {
    signal: AbortSignal;
    onProgress?: (status: "hashing" | "uploading" | "validating") => void;
  },
): Promise<ConversationAttachment> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  options.onProgress?.("hashing");
  const sha256 = await fileSha256(file);
  const scope = {
    tenant_id: configuration.tenantId,
    user_id: configuration.userId,
    conversation_id: conversationId,
  };
  const startResponse = await fetch(`${configuration.apiUrl}/api/v1/attachments/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({
      ...scope,
      file_name: file.name,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
      sha256,
    }),
  });
  if (!startResponse.ok) throw await responseError(startResponse, "Could not start attachment upload.");
  const started = await startResponse.json() as AttachmentUploadStartResponse;
  if (!started.upload_required && started.attachment) {
    return attachmentFromResponse(started.attachment);
  }
  if (!started.upload || !started.upload_id) {
    throw new Error("Attachment upload did not return a storage destination.");
  }

  options.onProgress?.("uploading");
  const uploadResponse = await fetch(started.upload.url, {
    method: started.upload.method,
    headers: started.upload.headers,
    body: file,
    signal: options.signal,
  });
  if (!uploadResponse.ok) {
    throw new Error(`Object storage rejected the attachment (${uploadResponse.status}).`);
  }

  options.onProgress?.("validating");
  const completeResponse = await fetch(
    `${configuration.apiUrl}/api/v1/attachments/uploads/${encodeURIComponent(started.upload_id)}/complete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: options.signal,
      body: JSON.stringify(scope),
    },
  );
  if (!completeResponse.ok) {
    throw await responseError(completeResponse, "Could not validate the uploaded attachment.");
  }
  return attachmentFromResponse(await completeResponse.json() as AttachmentMetadataResponse);
}

export async function releaseConversationAttachment(
  attachmentId: string,
  conversationId: string,
): Promise<void> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();
  const query = new URLSearchParams({
    tenant_id: configuration.tenantId,
    user_id: configuration.userId,
    conversation_id: conversationId,
  });
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/attachments/${encodeURIComponent(attachmentId)}?${query}`,
    { method: "DELETE" },
  );
  if (!response.ok && response.status !== 404) {
    throw await responseError(response, "Could not remove the attachment.");
  }
}

async function fileSha256(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function attachmentFromResponse(value: AttachmentMetadataResponse): ConversationAttachment {
  return {
    id: value.id,
    fileName: value.file_name,
    contentType: value.content_type,
    sizeBytes: value.size_bytes,
    mode: value.mode,
    status: value.status,
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
