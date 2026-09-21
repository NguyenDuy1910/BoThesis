import { getApiUrl } from "@/lib/api/config";
import { getAuthSession, storeAuthSession, type AuthSession } from "@/lib/auth/session";
import { migrateConversationUser } from "@/modules/chat/conversations";

export async function completeGoogleSignIn(credential: string): Promise<AuthSession> {
  const current = getAuthSession();
  return requestSession(
    { method: "google", credential },
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Google sign-in could not be completed.",
  );
}

export async function completePasswordSignIn(email: string, password: string): Promise<AuthSession> {
  const current = getAuthSession();
  return requestSession(
    { method: "password", email, password },
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Email or password is incorrect.",
  );
}

export async function createPasswordAccount(input: {
  username?: string;
  email: string;
  password: string;
  display_name?: string;
}): Promise<AuthSession> {
  const current = getAuthSession();
  const body: Record<string, string> = {
    ...input,
    ...(input.username?.trim() ? { username: input.username.trim() } : {}),
  };
  delete body.username;
  if (input.username?.trim()) body.username = input.username.trim();
  return requestSession(
    body,
    current?.session_kind === "guest" ? current.access_token : undefined,
    "Account could not be created.",
    "POST",
    "/api/v1/auth/accounts",
  );
}

export async function createSession(): Promise<AuthSession> {
  return requestSession({ method: "guest" });
}

export async function switchWorkspace(workspaceId: string): Promise<AuthSession> {
  const current = getAuthSession();
  if (!current) throw new Error("Your session has expired. Please sign in again.");
  return requestSession(
    { active_workspace_id: workspaceId },
    current.access_token,
    "Your workspace could not be changed.",
    "PATCH",
    "/api/v1/auth/session",
  );
}

async function requestSession(
  body: Record<string, string>,
  accessToken?: string,
  fallbackError = "Sign-in could not be completed.",
  method = "POST",
  path = "/api/v1/auth/sessions",
): Promise<AuthSession> {
  const apiUrl = getApiUrl();
  if (!apiUrl) {
    throw new Error("Sign-in is unavailable because the BoThesis API URL is not configured.");
  }
  const response = await fetch(`${apiUrl}${path}`, {
    method,
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
      previous.active_workspace_id,
      next.user_id,
      next.active_workspace_id,
    );
  }
  storeAuthSession(next);
  return next;
}
