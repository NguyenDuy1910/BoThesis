"use client";

import { useSyncExternalStore } from "react";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { mockApi } from "@/mocks/bothesis-api.mock";

/** Feature reads keep the temporary implementation out of page composition. */
export function useAdminData<T>(read: () => Promise<T>) {
  const revision = useSyncExternalStore(mockApi.subscribe, mockApi.revision, () => 0);
  return useApiQuery(read, revision);
}
export const adminData = mockApi;
