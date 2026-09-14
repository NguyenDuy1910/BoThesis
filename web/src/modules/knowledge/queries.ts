"use client";
import { useSyncExternalStore } from "react";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { mockApi } from "@/mocks/bothesis-api.mock";

export function useKnowledge() {
  const revision = useSyncExternalStore(mockApi.subscribe, mockApi.revision, () => 0);
  return useApiQuery(async () => ({ documents: await mockApi.knowledge.documents(), sources: await mockApi.knowledge.sources(), runs: await mockApi.knowledge.runs() }), revision);
}
export const knowledgeActions = mockApi.knowledge;
