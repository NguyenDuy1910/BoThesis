import { getBothesisChatConfiguration } from "@/lib/api/config";

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

export async function adminRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) {
    throw new AdminApiError(
      "Admin access is not configured. Set the BoThesis API, tenant, and user environment values.",
    );
  }
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/admin${path.startsWith("/") ? path : `/${path}`}`,
    {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Bothesis-Tenant-Id": configuration.tenantId,
        "X-Bothesis-User-Id": configuration.userId,
        ...init.headers,
      },
    },
  );
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = typeof payload?.detail === "string"
      ? payload.detail
      : `Admin request failed with status ${response.status}`;
    throw new AdminApiError(detail, response.status);
  }
  return payload as T;
}

export function queryString(values: Record<string, string | number | null | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
