import { getAuthSession } from "@/lib/auth/session";

export interface ApiConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
  accessToken?: string;
}

export function getApiConfiguration(): ApiConfiguration | null {
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  if (!apiUrl) return null;
  const session = getAuthSession();
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
