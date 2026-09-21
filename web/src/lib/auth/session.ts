import { invalidateApiData } from "@/lib/api/revision";

export interface AuthWorkspace {
  id: string;
  code: string;
  name: string;
  role_codes: string[];
  permissions: string[];
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  session_id: string;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  active_workspace_id: string;
  permissions: string[];
  workspaces: AuthWorkspace[];
  platform_permissions: string[];
  session_kind: "user" | "guest";
}

const storageKey = "bothesis.auth.session";

/**
 * Keep the browser's navigation decisions aligned with the authorization
 * semantics enforced by the API. The token carries the caller's resolved
 * permissions in full, so there is no wildcard to interpret here either.
 */
export function hasSessionPermission(
  session: AuthSession | null,
  permission: string,
): boolean {
  if (!session) return false;
  return session.permissions.includes(permission);
}

/** A surface is available when any of its governing permissions is granted. */
export function hasAnySessionPermission(
  session: AuthSession | null,
  permissions: readonly string[],
): boolean {
  return permissions.some((permission) => hasSessionPermission(session, permission));
}

/** Platform capability is its own scope, never implied by a workspace role. */
export function hasPlatformPermission(
  session: AuthSession | null,
  permission: string,
): boolean {
  return Boolean(session?.platform_permissions.includes(permission));
}

export const PLATFORM_CONTROL_PERMISSIONS = [
  "platform.tenant.read",
  "platform.user.read",
  "platform.audit.read",
  "platform.health.read",
] as const;

/** The platform console is available to anyone holding any platform grant. */
export function canAccessPlatformControl(session: AuthSession | null): boolean {
  return PLATFORM_CONTROL_PERMISSIONS.some((permission) =>
    hasPlatformPermission(session, permission),
  );
}

export function getAuthSession(): AuthSession | null {
  return getStoredAuthSession();
}

export function isGuestSession(session: AuthSession | null): boolean {
  return session?.session_kind === "guest";
}

/** The authenticated browser session, or null when nobody is signed in. */
export function getStoredAuthSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  const serialized = window.sessionStorage.getItem(storageKey);
  if (!serialized) return null;
  try {
    const session = JSON.parse(serialized) as unknown;
    if (!isAuthSession(session) || Date.parse(session.expires_at) <= Date.now()) {
      window.sessionStorage.removeItem(storageKey);
      return null;
    }
    return session;
  } catch {
    window.sessionStorage.removeItem(storageKey);
    return null;
  }
}

export function storeAuthSession(session: AuthSession): void {
  if (typeof window === "undefined" || !isAuthSession(session)) {
    throw new Error("The sign-in response did not contain a valid session.");
  }
  window.sessionStorage.setItem(storageKey, JSON.stringify(session));
  // Views hold the previous workspace's rows until they are told to read again.
  invalidateApiData();
}

export function clearAuthSession(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(storageKey);
  invalidateApiData();
}

function isAuthSession(value: unknown): value is AuthSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<AuthSession>;
  return (
    typeof session.access_token === "string" &&
    session.access_token.length > 0 &&
    session.token_type === "bearer" &&
    typeof session.expires_at === "string" &&
    !Number.isNaN(Date.parse(session.expires_at)) &&
    typeof session.session_id === "string" &&
    session.session_id.length > 0 &&
    (session.user_id === null || typeof session.user_id === "string") &&
    (session.email === null || typeof session.email === "string") &&
    typeof session.active_workspace_id === "string" &&
    Array.isArray(session.permissions) &&
    Array.isArray(session.workspaces) &&
    Array.isArray(session.platform_permissions) &&
    (session.session_kind === "user" || session.session_kind === "guest") &&
    (session.session_kind === "guest" ? session.user_id === null : typeof session.user_id === "string")
  );
}
