"use client";

import { useSyncExternalStore } from "react";

import { apiRevision, invalidateApiData, subscribeApiData } from "@/lib/api/revision";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { uploadCollectionFile } from "@/modules/admin/api";
import { knowledgeApi } from "@/modules/knowledge/knowledge-api";
import { toWorkspaceDocument } from "@/modules/knowledge/view-model";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

export interface LibrarySnapshot {
  collectionId: string | null;
  collectionTitle: string;
  documents: WorkspaceKnowledgeDocument[];
}

/**
 * The caller's own documents.
 *
 * Every workspace gives each member one private Collection, which is where
 * their uploads and the documents a conversation produced are kept. That
 * Collection is the library: there is no second place personal files live.
 */
export function useLibrary() {
  const revision = useSyncExternalStore(subscribeApiData, apiRevision, () => 0);
  return useApiQuery<LibrarySnapshot>(async () => {
    const home = await knowledgeApi.home();
    const collectionId = home.personal_collection_id;
    if (!collectionId) {
      return { collectionId: null, collectionTitle: "My documents", documents: [] };
    }
    const page = await knowledgeApi.collection(collectionId);
    return {
      collectionId,
      collectionTitle: page.collection.title,
      documents: page.documents.map((document) =>
        toWorkspaceDocument(document, page.collection.title),
      ),
    };
  }, revision);
}

export const libraryActions = {
  async upload(file: File, collectionId: string | null) {
    const targetCollectionId = collectionId
      ?? (await knowledgeApi.ensurePersonalCollection()).id;
    await uploadCollectionFile(targetCollectionId, file, {
      idempotencyKey: crypto.randomUUID(),
    });
    invalidateApiData();
  },
};
