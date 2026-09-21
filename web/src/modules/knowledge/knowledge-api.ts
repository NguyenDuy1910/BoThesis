/** The knowledge workspace endpoints: Collections, and the Items inside them. */

import { apiRequest } from "@/lib/api/request";
import type { ApiKnowledgeCollection, ApiKnowledgeDocument } from "@/modules/knowledge/view-model";

export interface KnowledgeHome {
  collections: ApiKnowledgeCollection[];
  recent_documents: ApiKnowledgeDocument[];
  personal_collection_id: string | null;
}

export interface KnowledgeCollectionPage {
  collection: ApiKnowledgeCollection;
  child_collections: ApiKnowledgeCollection[];
  documents: ApiKnowledgeDocument[];
  total: number;
  page: number;
  page_size: number;
}

export const knowledgeApi = {
  home: async (): Promise<KnowledgeHome> => {
    const value = await apiRequest<{ collections: ContractCollection[]; recent_documents: ContractDocument[]; personal_collection_id: string | null }>("/knowledge/home");
    return { collections: value.collections.map(toCollection), recent_documents: value.recent_documents.map(toDocument), personal_collection_id: value.personal_collection_id };
  },
  collection: async (collectionId: string, page = 1): Promise<KnowledgeCollectionPage> => {
    const [collection, documents] = await Promise.all([
      apiRequest<ContractCollection>(`/collections/${encodeURIComponent(collectionId)}`),
      apiRequest<{ items: ContractDocument[]; total: number; page: number; page_size: number }>(`/documents?collection_id=${encodeURIComponent(collectionId)}&page=${page}&page_size=100`),
    ]);
    return { collection: toCollection(collection), child_collections: [], documents: documents.items.map(toDocument), total: documents.total, page: documents.page, page_size: documents.page_size };
  },
  createCollection: (title: string, description?: string) =>
    apiRequest<{ id: string; title: string }>("/collections", {
      method: "POST",
      body: JSON.stringify({ title, description }),
    }),
  ensurePersonalCollection: () =>
    apiRequest<{ id: string; title: string }>("/collections/personal", {
      method: "PUT",
  }),
};

interface ContractCollection { id: string; title: string; description: string | null; parent_collection_id: string | null; document_count: number; source_count: number; updated_at: string; }
interface ContractDocument { id: string; name: string; content_type: string; status: "pending_content" | "available" | "failed"; updated_at: string; }
const toCollection = (v: ContractCollection): ApiKnowledgeCollection => ({ ...v, parent_item_id: v.parent_collection_id });
const toDocument = (v: ContractDocument): ApiKnowledgeDocument => ({ id: v.id, title: v.name, content_type: v.content_type, document_type: null, status: v.status === "available" ? "ready" : v.status === "failed" ? "failed" : "pending", updated_at: v.updated_at });
