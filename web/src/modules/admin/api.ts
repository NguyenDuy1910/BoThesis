"use client";

import { getBothesisChatConfiguration } from "@/lib/api/config";
import { useCallback, useEffect, useState } from "react";

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

/**
 * Shared request state for the client-side Admin control plane. Keeping this
 * next to the request boundary gives every admin surface the same cancellation
 * and retry behaviour without duplicating fetch effects.
 */
export function useAdminQuery<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    adminRequest<T>(path, { signal: controller.signal })
      .then(setData)
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "The Admin request could not be completed.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);

  return { data, error, loading, reload };
}

/** Upload one managed-source file while exposing real browser upload progress. */
export function uploadDatasourceFile<T>(
  connectorId: string,
  file: File,
  options: { onProgress?: (percent: number) => void; signal?: AbortSignal } = {},
): Promise<T> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) {
    return Promise.reject(new AdminApiError(
      "Admin access is not configured. Set the BoThesis API, tenant, and user environment values.",
    ));
  }

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const url = `${configuration.apiUrl}/api/v1/admin/datasources/${encodeURIComponent(connectorId)}/files`;
    const abort = () => request.abort();
    options.signal?.addEventListener("abort", abort, { once: true });
    request.open("PUT", url);
    request.responseType = "json";
    request.setRequestHeader("Accept", "application/json");
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.setRequestHeader("X-Bothesis-Tenant-Id", configuration.tenantId);
    request.setRequestHeader("X-Bothesis-User-Id", configuration.userId);
    request.setRequestHeader("X-Bothesis-File-Name", encodeURIComponent(file.name));
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new AdminApiError("File upload could not reach the Admin API."));
    request.onabort = () => reject(new DOMException("The upload was cancelled.", "AbortError"));
    request.onload = () => {
      options.signal?.removeEventListener("abort", abort);
      const payload = request.response as { detail?: unknown } | T | null;
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as T);
        return;
      }
      const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
        ? payload.detail
        : `File upload failed with status ${request.status}`;
      reject(new AdminApiError(detail, request.status));
    };
    request.send(file);
  });
}
