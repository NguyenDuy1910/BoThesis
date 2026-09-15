"use client";

import { useSyncExternalStore } from "react";

import { apiRevision, subscribeApiData } from "@/lib/api/revision";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { getAuthSession } from "@/lib/auth/session";

/**
 * The workspaces this person may switch to.
 *
 * They come from the session the API issued: a token carries exactly the
 * memberships it was minted for, so the switcher can never offer a workspace
 * the server would then refuse.
 */
export function useWorkspaces() {
  const revision = useSyncExternalStore(subscribeApiData, apiRevision, () => 0);
  return useApiQuery(async () => getAuthSession()?.tenants ?? [], revision);
}
