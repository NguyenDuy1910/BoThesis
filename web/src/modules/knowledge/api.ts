import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import type {
  KnowledgeCitationResponse,
  KnowledgeCollectionWorkspace,
  KnowledgeDocumentSummary,
  KnowledgeHome,
  KnowledgeItemViewer,
  KnowledgeSearchResult,
} from "./types";

/** A viewer request failed before any source content was exposed. */
export class KnowledgeViewerRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function getKnowledgeItemViewer(
  itemId: string,
  chunkId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeItemViewer> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const query = chunkId ? `?chunk=${encodeURIComponent(chunkId)}` : "";
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/items/${encodeURIComponent(itemId)}${query}`,
    {
      cache: "no-store",
      headers: requestIdentityHeaders(configuration),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new KnowledgeViewerRequestError(
      response.status,
      detail || `Could not open this knowledge item (${response.status}).`,
    );
  }
  return await response.json() as KnowledgeItemViewer;
}

export async function getKnowledgeCitation(
  itemId: string,
  chunkId: string,
  signal?: AbortSignal,
): Promise<KnowledgeCitationResponse> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/items/${encodeURIComponent(itemId)}/citations/${encodeURIComponent(chunkId)}`,
    {
      cache: "no-store",
      headers: requestIdentityHeaders(configuration),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Could not resolve this citation (${response.status}).`);
  }
  return await response.json() as KnowledgeCitationResponse;
}

/** Lists only Collections and source Items the current identity can browse. */
export async function getKnowledgeHome(signal?: AbortSignal): Promise<KnowledgeHome> {
  return knowledgeRequest<KnowledgeHome>("/api/v1/knowledge/collections", { signal });
}

export async function getKnowledgeCollectionWorkspace(
  collectionId: string,
  options: {
    search?: string;
    page?: number;
    pageSize?: number;
    signal?: AbortSignal;
  } = {},
): Promise<KnowledgeCollectionWorkspace> {
  const query = new URLSearchParams();
  if (options.search?.trim()) query.set("search", options.search.trim());
  if (options.page && options.page > 1) query.set("page", String(options.page));
  if (options.pageSize && options.pageSize !== 50) query.set("page_size", String(options.pageSize));
  const suffix = query.size ? `?${query.toString()}` : "";
  return knowledgeRequest<KnowledgeCollectionWorkspace>(
    `/api/v1/knowledge/collections/${encodeURIComponent(collectionId)}${suffix}`,
    { signal: options.signal },
  );
}

export async function searchKnowledge(
  query: string,
  collectionId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeSearchResult[]> {
  const value = query.trim();
  if (!value) return [];
  const result = await knowledgeRequest<{ results: KnowledgeSearchResult[] }>(
    "/api/v1/documents/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: value,
        top_k: 12,
        collection_item_ids: collectionId ? [collectionId] : undefined,
      }),
      signal,
    },
  );
  return result.results;
}

/** Creates a governed Collection while keeping the person in Knowledge. */
export async function createKnowledgeCollection(
  input: { title: string; description?: string },
  signal?: AbortSignal,
): Promise<{ id: string; title: string }> {
  return knowledgeRequest<{ id: string; title: string }>(
    "/api/v1/knowledge/collections",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: input.title.trim(),
        description: input.description?.trim() || undefined,
      }),
      signal,
    },
  );
}

/** Uploads native content directly into an authorized Collection for indexing. */
export async function uploadKnowledgeCollectionDocument(
  collectionId: string,
  file: File,
  signal?: AbortSignal,
): Promise<KnowledgeDocumentSummary> {
  const body = new FormData();
  body.append("file", file);
  const result = await knowledgeRequest<{ document: {
    id: string;
    file_name: string;
    content_type: string;
    status: KnowledgeDocumentSummary["status"];
    created_at: string;
  } }>(
    `/api/v1/collections/${encodeURIComponent(collectionId)}/documents/upload`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body,
      signal,
    },
  );
  return {
    id: result.document.id,
    title: result.document.file_name,
    content_type: result.document.content_type,
    status: result.document.status,
    updated_at: result.document.created_at,
  };
}

async function knowledgeRequest<T>(path: string, init: RequestInit): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new Error("Knowledge workspace is not configured.");
  const response = await fetch(`${configuration.apiUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...requestIdentityHeaders(configuration),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      errorDetail(detail) || `Knowledge workspace request failed (${response.status}).`,
    );
  }
  return await response.json() as T;
}

function errorDetail(value: string) {
  try {
    const payload = JSON.parse(value) as { detail?: unknown };
    return typeof payload.detail === "string" ? payload.detail : value;
  } catch {
    return value;
  }
}
