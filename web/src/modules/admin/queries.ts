"use client";

import { useSyncExternalStore } from "react";

import { apiRevision, subscribeApiData } from "@/lib/api/revision";
import { useApiQuery } from "@/lib/hooks/useApiQuery";

/**
 * An Admin read that refetches whenever an Admin write elsewhere invalidates.
 *
 * Pages pass the request function rather than a path so a screen can compose
 * several endpoints into the one shape it renders.
 */
export function useAdminData<T>(read: () => Promise<T>) {
  const revision = useSyncExternalStore(subscribeApiData, apiRevision, () => 0);
  return useApiQuery(read, revision);
}
