"use client";

import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import { appBrand } from "@/lib/brand";

/**
 * One request boundary for every production route.
 *
 * Surfaces differ in what they ask for, not in how they ask: the same identity
 * headers, the same JSON handling, and the same failure shape, so an operator
 * reading an error never has to know which screen produced it.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True when the API says the account behind a connection must authorize again. */
export function needsReauthorization(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) {
    throw new ApiError(
      `${appBrand.productName} is not configured. Set the API, tenant, and user environment values.`,
    );
  }
  let response: Response;
  try {
    response = await fetch(
      `${configuration.apiUrl}/api/v1${path.startsWith("/") ? path : `/${path}`}`,
      {
        ...init,
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          ...requestIdentityHeaders(configuration),
          ...init.headers,
        },
      },
    );
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(
      `The ${appBrand.productName} API could not be reached. Check the API address and try again.`,
    );
  }
  if (response.status === 204) return undefined as T;
  const payload = (await response.json().catch(() => null)) as
    | { detail?: unknown }
    | null;
  if (!response.ok) {
    // The API writes its own operator-facing detail; a status code alone tells
    // the reader nothing they can act on.
    const detail = typeof payload?.detail === "string"
      ? payload.detail
      : `The request failed with status ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return payload as T;
}

export function queryString(
  values: Record<string, string | number | boolean | null | undefined>,
) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
