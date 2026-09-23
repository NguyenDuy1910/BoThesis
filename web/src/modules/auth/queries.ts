"use client";

import { useCallback, useRef, useState, useSyncExternalStore } from "react";

import { apiRevision, subscribeApiData } from "@/lib/api/revision";
import { getAuthSession } from "@/lib/auth/session";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { switchWorkspace as requestWorkspaceSwitch } from "@/modules/auth/api";

/**
 * The workspaces this person may switch to.
 *
 * They come from the session the API issued: a token carries exactly the
 * memberships it was minted for, so the switcher can never offer a workspace
 * the server would then refuse.
 */
export function useWorkspaces() {
  const revision = useSyncExternalStore(subscribeApiData, apiRevision, () => 0);
  return useApiQuery(async () => getAuthSession()?.workspaces ?? [], revision);
}

/**
 * Switch exactly one workspace at a time and retain a recoverable error beside
 * the control that initiated the change.
 */
export function useWorkspaceSwitch() {
  const requestInFlight = useRef(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const switchWorkspace = useCallback(async (workspaceId: string) => {
    const current = getAuthSession();
    if (!current) {
      setError("Your session has expired. Please sign in again.");
      return false;
    }
    if (workspaceId === current.active_workspace_id) return true;
    if (requestInFlight.current) return false;

    requestInFlight.current = true;
    setSwitchingId(workspaceId);
    setError(null);
    try {
      await requestWorkspaceSwitch(workspaceId);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not change workspace.");
      return false;
    } finally {
      requestInFlight.current = false;
      setSwitchingId(null);
    }
  }, []);

  return { error, switchingId, switchWorkspace };
}
