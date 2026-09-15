import { getAuthSession, getStoredAuthSession } from "@/lib/auth/session";

export interface ApiConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
  accessToken?: string;
}

export function getApiConfiguration(): ApiConfiguration | null {
  return resolveApiConfiguration(getAuthSession());
}

/**
 * Use for surfaces that are already backed by production routes. Unlike the
 * broader preview configuration, it never turns mock session state into API
 * credentials.
 */
export function getLiveApiConfiguration(): ApiConfiguration | null {
  return resolveApiConfiguration(getStoredAuthSession());
}

function resolveApiConfiguration(session: ReturnType<typeof getAuthSession>): ApiConfiguration | null {
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  if (!apiUrl) return null;
  if (session) {
    return {
      apiUrl,
      tenantId: session.active_tenant_id,
      userId: session.user_id,
      accessToken: session.access_token,
    };
  }
  const tenantId = process.env.NEXT_PUBLIC_BOTHESIS_TENANT_ID?.trim();
  const userId = process.env.NEXT_PUBLIC_BOTHESIS_USER_ID?.trim();
  if (!tenantId || !userId) return null;
  return { apiUrl, tenantId, userId };
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
