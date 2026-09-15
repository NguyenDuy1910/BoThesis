/** The knowledge workspace endpoints: Collections, and the Items inside them. */

import { apiRequest } from "@/lib/api/request";
import type { ApiKnowledgeCollection, ApiKnowledgeDocument } from "@/modules/knowledge/view-model";

export interface KnowledgeHome {
  items: ApiKnowledgeCollection[];
  total: number;
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
  home: () => apiRequest<KnowledgeHome>("/knowledge/collections"),
  collection: (collectionId: string, page = 1) =>
    apiRequest<KnowledgeCollectionPage>(
      `/knowledge/collections/${encodeURIComponent(collectionId)}?page=${page}&page_size=100`,
    ),
  createCollection: (title: string, description?: string) =>
    apiRequest<{ id: string; title: string }>("/knowledge/collections", {
      method: "POST",
      body: JSON.stringify({ title, description }),
    }),
};
