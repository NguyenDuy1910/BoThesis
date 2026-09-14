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
import { adminRequest } from "@/modules/admin/api";
import { mockApi, previewMode } from "@/mocks/bothesis-api.mock";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

export interface AdminTenant {
  id: string;
  code: string;
  name: string;
  status: string;
  updated_at: string;
}

export interface AdminOverview {
  tenant?: AdminTenant;
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

export interface AdminViewer {
  id: string;
  email: string;
  display_name: string | null;
  membership?: { role?: { display_name?: string; code?: string } } | null;
}

interface AdminWorkspaceValue {
  overview: AdminOverview | null;
  viewer: AdminViewer | null;
  tenant: AdminTenant | null;
  loading: boolean;
  error: string | null;
  /** Total of every attention counter, used for the sidebar badge. */
  attentionCount: number;
  reload: () => void;
}

const AdminWorkspaceContext = createContext<AdminWorkspaceValue | null>(null);

/**
 * The workspace identity the whole console renders around. Loaded once at the
 * shell so the sidebar, header and dashboard agree on which tenant they are
 * looking at instead of each fetching it again.
 */
export function AdminWorkspaceProvider({ children }: { children: React.ReactNode }) {
  const currentSession = useAuthSession();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [viewer, setViewer] = useState<AdminViewer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    if (previewMode) {
      setLoading(true);
      void mockApi.workspaces.get().then((workspace) => {
        if (controller.signal.aborted) return;
        setOverview({ tenant: { id: workspace.id, code: workspace.id, name: workspace.name, status: workspace.status, updated_at: "2026-09-14" } });
        setViewer(currentSession ? { id: currentSession.user_id, display_name: currentSession.display_name, email: currentSession.email } : null);
        setLoading(false);
      });
      return () => controller.abort();
    }
    const configuration = getApiConfiguration();
    const session = getAuthSession();
    const userId = configuration?.userId;
    const canViewOverview = hasSessionPermission(session, "admin");
    const canViewPeople = hasSessionPermission(session, "user.manage");
    const sessionViewer = session
      ? {
          id: session.user_id,
          email: session.email,
          display_name: session.display_name,
        }
      : null;
    setLoading(true);
    setError(null);

    Promise.all([
      canViewOverview
        ? adminRequest<AdminOverview>("/overview", { signal: controller.signal })
        : Promise.resolve(null),
      userId && canViewPeople
        ? adminRequest<AdminViewer>(`/users/${userId}`, {
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

  const value = useMemo<AdminWorkspaceValue>(() => {
    const attention = overview?.attention ?? {};
    const attentionCount = Object.values(attention).reduce<number>(
      (total, entry) => total + (typeof entry === "number" ? entry : 0),
      0,
    );
    return {
      overview,
      viewer,
      tenant: overview?.tenant ?? null,
      loading,
      error,
      attentionCount,
      reload,
    };
  }, [error, loading, overview, reload, viewer]);

  return (
    <AdminWorkspaceContext.Provider value={value}>
      {children}
    </AdminWorkspaceContext.Provider>
  );
}

export function useAdminWorkspace() {
  const value = useContext(AdminWorkspaceContext);
  if (!value) {
    throw new Error("useAdminWorkspace must be used inside AdminWorkspaceProvider");
  }
  return value;
}

export function viewerName(viewer: AdminViewer | null) {
  return viewer?.display_name || viewer?.email || "Signed in";
}
