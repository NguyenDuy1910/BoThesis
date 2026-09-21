import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import type {
  KnowledgeCitationResponse,
  KnowledgeCollectionSummary,
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
    `${configuration.apiUrl}/api/v1/knowledge/documents/${encodeURIComponent(itemId)}${query}`,
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
    `${configuration.apiUrl}/api/v1/knowledge/documents/${encodeURIComponent(itemId)}/citations/${encodeURIComponent(chunkId)}`,
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
  const value = await knowledgeRequest<{
    collections: ContractCollection[];
    recent_documents: ContractDocument[];
    personal_collection_id: string | null;
  }>("/api/v1/knowledge/home", { signal });
  return {
    collections: value.collections.map(collectionSummary),
    recent_documents: value.recent_documents.map(documentSummary),
    personal_collection_id: value.personal_collection_id,
  };
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
  const query = new URLSearchParams({
    collection_id: collectionId,
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 50),
  });
  if (options.search?.trim()) query.set("search", options.search.trim());
  const [collection, collectionPage, documentPage] = await Promise.all([
    knowledgeRequest<ContractCollection>(`/api/v1/collections/${encodeURIComponent(collectionId)}`, { signal: options.signal }),
    knowledgeRequest<{ items: ContractCollection[] }>("/api/v1/collections?page_size=100", { signal: options.signal }),
    knowledgeRequest<{ items: ContractDocument[]; total: number; page: number; page_size: number }>(`/api/v1/documents?${query.toString()}`, { signal: options.signal }),
  ]);
  return {
    collection: collectionSummary(collection),
    child_collections: collectionPage.items.filter((item) => item.parent_collection_id === collectionId).map(collectionSummary),
    documents: documentPage.items.map(documentSummary),
    total: documentPage.total,
    page: documentPage.page,
    page_size: documentPage.page_size,
  };
}

export async function searchKnowledge(
  query: string,
  collectionId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeSearchResult[]> {
  const value = query.trim();
  if (!value) return [];
  const result = await knowledgeRequest<{ items: KnowledgeSearchResult[] }>(
    "/api/v1/documents/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: value,
        top_k: 12,
        collection_ids: collectionId ? [collectionId] : undefined,
      }),
      signal,
    },
  );
  return result.items;
}

/** Creates a governed Collection while keeping the person in Knowledge. */
export async function createKnowledgeCollection(
  input: { title: string; description?: string },
  signal?: AbortSignal,
): Promise<{ id: string; title: string }> {
  return knowledgeRequest<{ id: string; title: string }>(
    "/api/v1/collections",
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
    name: string;
    content_type: string;
    status: "pending_content" | "available" | "failed";
    created_at: string;
  } }>(
    `/api/v1/collections/${encodeURIComponent(collectionId)}/documents`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body,
      signal,
    },
  );
  return {
    id: result.document.id,
    title: result.document.name,
    content_type: result.document.content_type,
    status: result.document.status === "available" ? "ready" : result.document.status === "failed" ? "failed" : "pending",
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

interface ContractCollection {
  id: string;
  title: string;
  description: string | null;
  parent_collection_id: string | null;
  document_count: number;
  source_count: number;
  updated_at: string;
}

interface ContractDocument {
  id: string;
  name: string;
  content_type: string;
  status: "pending_content" | "available" | "failed";
  updated_at: string;
}

function collectionSummary(value: ContractCollection): KnowledgeCollectionSummary {
  return { ...value, parent_item_id: value.parent_collection_id };
}

function documentSummary(value: ContractDocument): KnowledgeDocumentSummary {
  return {
    id: value.id,
    title: value.name,
    content_type: value.content_type,
    status: value.status === "available" ? "ready" : value.status === "failed" ? "failed" : "pending",
    updated_at: value.updated_at,
  };
}
