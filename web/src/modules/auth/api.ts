import { getAuthSession, storeAuthSession, type AuthSession } from "@/lib/auth/session";
import { mockApi, previewMode } from "@/mocks/bothesis-api.mock";

export async function completeGoogleSignIn(credential: string): Promise<AuthSession> {
  return requestSession("/api/auth/google", { credential });
}

export async function switchWorkspace(tenantId: string): Promise<AuthSession> {
  if (previewMode) return mockApi.session.switchWorkspace(tenantId);
  const current = getAuthSession();
  if (!current) throw new Error("Your session has expired. Please sign in again.");
  return requestSession("/api/auth/session", { tenant_id: tenantId }, current.access_token);
}

async function requestSession(
  path: string,
  body: Record<string, string>,
  accessToken?: string,
): Promise<AuthSession> {
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  if (!apiUrl) {
    throw new Error("Sign-in is unavailable because the BoThesis API URL is not configured.");
  }
  const response = await fetch(`${apiUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null) as AuthSession | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
      ? payload.detail
      : "Google sign-in could not be completed.";
    throw new Error(detail);
  }
  storeAuthSession(payload as AuthSession);
  return payload as AuthSession;
}
