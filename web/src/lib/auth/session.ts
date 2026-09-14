import { mockApi, previewMode } from "@/mocks/bothesis-api.mock";

export interface AuthTenant {
  id: string;
  code: string;
  name: string;
  role_id: string | null;
  role_code: string;
  permissions: string[];
}

export interface AuthSession {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user_id: string;
  email: string;
  display_name: string | null;
  active_tenant_id: string;
  permissions: string[];
  tenants: AuthTenant[];
  platform_scopes: string[];
}

const storageKey = "bothesis.auth.session";

/**
 * Keep the browser's navigation decisions aligned with the authorization
 * semantics enforced by the API. `admin` and `*:*` are tenant-wide grants.
 */
export function hasSessionPermission(
  session: AuthSession | null,
  permission: string,
): boolean {
  if (!session) return false;
  return session.permissions.includes("*:*") ||
    session.permissions.includes("admin") ||
    session.permissions.includes(permission);
}

/** A surface is available when any of its governing permissions is granted. */
export function hasAnySessionPermission(
  session: AuthSession | null,
  permissions: readonly string[],
): boolean {
  return permissions.some((permission) => hasSessionPermission(session, permission));
}

export function hasPlatformScope(
  session: AuthSession | null,
  scope: string,
): boolean {
  return Boolean(session?.platform_scopes.includes(scope));
}

export function getAuthSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  if (previewMode) return mockApi.session.current();
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
}

export function clearAuthSession(): void {
  if (previewMode) { mockApi.session.signOut(); return; }
  if (typeof window !== "undefined") window.sessionStorage.removeItem(storageKey);
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
    typeof session.user_id === "string" &&
    typeof session.email === "string" &&
    typeof session.active_tenant_id === "string" &&
    Array.isArray(session.permissions) &&
    Array.isArray(session.tenants) &&
    Array.isArray(session.platform_scopes)
  );
}
