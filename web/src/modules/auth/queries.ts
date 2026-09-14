"use client";
import { useSyncExternalStore } from "react";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { mockApi } from "@/mocks/bothesis-api.mock";

export function useWorkspaces() {
  const revision = useSyncExternalStore(mockApi.subscribe, mockApi.revision, () => 0);
  return useApiQuery(mockApi.workspaces.list, revision);
}
