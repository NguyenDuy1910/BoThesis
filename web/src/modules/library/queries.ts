"use client";
import { useSyncExternalStore } from "react";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { mockApi } from "@/mocks/bothesis-api.mock";

export function useLibrary() {
  const revision = useSyncExternalStore(mockApi.subscribe, mockApi.revision, () => 0);
  return useApiQuery(async () => ({ documents: await mockApi.library.list(), collections: await mockApi.library.collections() }), revision);
}
export const libraryActions = mockApi.library;
