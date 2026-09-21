import { getStoredAuthSession } from "@/lib/auth/session";

const localDevelopmentApiUrl = "http://127.0.0.1:8000";
const localDevelopmentTenantId = "00000000-0000-0000-0000-000000000001";
const localDevelopmentUserId = "00000000-0000-0000-0000-000000000002";

export interface ApiConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
  accessToken?: string;
}

/**
 * How to reach the API as the current caller.
 *
 * A signed-in browser session authorizes with its own token. Falling back to
 * the configured development identity keeps local work possible before a
 * sign-in provider is set up, and is the only path that uses header identity.
 */
export function getApiConfiguration(): ApiConfiguration | null {
  return resolveApiConfiguration(getStoredAuthSession());
}

/**
 * The local backend has deterministic development identity and port defaults,
 * so starting the WebUI never depends on an ignored environment file. Public
 * configuration remains an explicit override for non-local environments.
 */
export function getApiUrl(): string | null {
  return configuredValue(process.env.NEXT_PUBLIC_BOTHESIS_API_URL)
    ?? (process.env.NODE_ENV === "development" ? localDevelopmentApiUrl : null);
}

function resolveApiConfiguration(session: ReturnType<typeof getStoredAuthSession>): ApiConfiguration | null {
  const apiUrl = getApiUrl();
  if (!apiUrl) return null;
  if (session) {
    return {
      apiUrl,
      tenantId: session.active_workspace_id,
      userId: session.user_id ?? session.session_id,
      accessToken: session.access_token,
    };
  }
  const localIdentity = process.env.NODE_ENV === "development";
  const tenantId = configuredValue(process.env.NEXT_PUBLIC_BOTHESIS_TENANT_ID)
    ?? (localIdentity ? localDevelopmentTenantId : undefined);
  const userId = configuredValue(process.env.NEXT_PUBLIC_BOTHESIS_USER_ID)
    ?? (localIdentity ? localDevelopmentUserId : undefined);
  if (!tenantId || !userId) return null;
  return { apiUrl, tenantId, userId };
}

function configuredValue(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized.replace(/\/$/, "") : undefined;
}

/** Browser sessions use JWT; explicit environment IDs preserve local development. */
export function requestIdentityHeaders(configuration: ApiConfiguration): Record<string, string> {
  if (configuration.accessToken) {
    return { Authorization: `Bearer ${configuration.accessToken}` };
  }
  return {
    "X-Bothesis-User-Id": configuration.userId,
    "X-Bothesis-Tenant-Id": configuration.tenantId,
  };
}
