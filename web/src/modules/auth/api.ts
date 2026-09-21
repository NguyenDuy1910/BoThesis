import { getApiUrl } from "@/lib/api/config";
import { getAuthSession, storeAuthSession, type AuthSession } from "@/lib/auth/session";
import { migrateConversationUser } from "@/modules/chat/conversations";

export async function completeGoogleSignIn(credential: string): Promise<AuthSession> {
  const current = getAuthSession();
  return requestSession(
    "/api/v1/auth/google",
    { credential },
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Google sign-in could not be completed.",
  );
}

export async function completePasswordSignIn(username: string, password: string): Promise<AuthSession> {
  const current = getAuthSession();
  return requestSession(
    "/api/v1/auth/password",
    { username, password },
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Username or password is incorrect.",
  );
}

export async function createPasswordAccount(input: {
  username: string;
  email: string;
  password: string;
  display_name?: string;
}): Promise<AuthSession> {
  const current = getAuthSession();
  return requestSession(
    "/api/v1/auth/accounts",
    input,
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Account could not be created.",
  );
}

export async function createGuestSession(): Promise<AuthSession> {
  return requestSession("/api/v1/auth/guest-sessions", {});
}

export async function switchWorkspace(tenantId: string): Promise<AuthSession> {
  const current = getAuthSession();
  if (!current) throw new Error("Your session has expired. Please sign in again.");
  return requestSession("/api/v1/auth/session", { tenant_id: tenantId }, current.access_token);
}

async function requestSession(
  path: string,
  body: Record<string, string>,
  accessToken?: string,
  fallbackError = "Sign-in could not be completed.",
): Promise<AuthSession> {
  const apiUrl = getApiUrl();
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
      : fallbackError;
    throw new Error(detail);
  }
  const next = payload as AuthSession;
  const previous = getAuthSession();
  if (previous?.session_kind === "guest" && next.session_kind === "user" && next.user_id) {
    migrateConversationUser(
      previous.session_id,
      previous.active_tenant_id,
      next.user_id,
      next.active_tenant_id,
    );
  }
  storeAuthSession(next);
  return next;
}
