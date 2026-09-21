"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { getApiConfiguration } from "@/lib/api/config";
import { getAuthSession, hasSessionPermission } from "@/lib/auth/session";
import { controlPlaneRequest } from "@/modules/workspace-control/control-plane-api";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

export interface WorkspaceSummary {
  id: string;
  code: string;
  name: string;
  status: string;
  updated_at: string;
}

export interface WorkspaceOverview {
  workspace?: WorkspaceSummary;
  metrics?: {
    active_users?: number;
    active_roles?: number;
    active_groups?: number;
    active_integration_connections?: number;
    active_datasources?: number;
    items?: number;
  } | null;
  attention?: Record<string, number | undefined> | null;
  recent_activity?: Record<string, unknown>[] | null;
  generated_at?: string;
}

export interface WorkspaceViewer {
  id: string;
  email: string;
  display_name: string | null;
  membership?: { role?: { display_name?: string; code?: string } } | null;
}

interface WorkspaceControlValue {
  overview: WorkspaceOverview | null;
  viewer: WorkspaceViewer | null;
  tenant: WorkspaceSummary | null;
  loading: boolean;
  error: string | null;
  /** Total of every attention counter, used for the sidebar badge. */
  attentionCount: number;
  reload: () => void;
}

const WorkspaceControlContext = createContext<WorkspaceControlValue | null>(null);

/**
 * The workspace identity the whole console renders around. Loaded once at the
 * shell so the sidebar, header and dashboard agree on which tenant they are
 * looking at instead of each fetching it again.
 */
export function WorkspaceControlProvider({ children }: { children: React.ReactNode }) {
  const currentSession = useAuthSession();
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [viewer, setViewer] = useState<WorkspaceViewer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const configuration = getApiConfiguration();
    const session = getAuthSession();
    const userId = configuration?.userId;
    const canViewOverview = hasSessionPermission(session, "tenant.read");
    const canViewPeople = hasSessionPermission(session, "user.manage");
    const sessionViewer = session?.user_id && session.email
      ? {
          id: session.user_id,
          email: session.email,
          display_name: session.display_name,
        }
      : null;
    setLoading(true);
    setError(null);

    Promise.all([
      canViewOverview && currentSession?.active_workspace_id
        ? controlPlaneRequest<WorkspaceOverview>(
            `/workspaces/${currentSession.active_workspace_id}/overview`,
            { signal: controller.signal },
          )
        : Promise.resolve(null),
      userId && canViewPeople
        ? controlPlaneRequest<WorkspaceViewer>(`/users/${userId}`, {
            signal: controller.signal,
          }).catch(() => null)
        : Promise.resolve(sessionViewer),
    ])
      .then(([nextOverview, nextViewer]) => {
        if (controller.signal.aborted) return;
        setOverview(nextOverview);
        setViewer(nextViewer);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof Error
            ? cause.message
            : "This workspace could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [revision, currentSession]);

  const value = useMemo<WorkspaceControlValue>(() => {
    const attention = overview?.attention ?? {};
    const attentionCount = Object.values(attention).reduce<number>(
      (total, entry) => total + (typeof entry === "number" ? entry : 0),
      0,
    );
    return {
      overview,
      viewer,
      tenant: overview?.workspace ?? null,
      loading,
      error,
      attentionCount,
      reload,
    };
  }, [error, loading, overview, reload, viewer]);

  return (
    <WorkspaceControlContext.Provider value={value}>
      {children}
    </WorkspaceControlContext.Provider>
  );
}

export function useWorkspaceControl() {
  const value = useContext(WorkspaceControlContext);
  if (!value) {
    throw new Error("useWorkspaceControl must be used inside WorkspaceControlProvider");
  }
  return value;
}

export function viewerName(viewer: WorkspaceViewer | null) {
  return viewer?.display_name || viewer?.email || "Signed in";
}
