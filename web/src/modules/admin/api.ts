"use client";

import { describeRequestFailure } from "@/lib/api/errors";
import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import { appBrand } from "@/lib/brand";
import { useCallback, useEffect, useRef, useState } from "react";

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
  const configuration = getApiConfiguration();
  if (!configuration) {
    throw new AdminApiError(
      `Admin access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
    );
  }
  let response: Response;
  try {
    response = await fetch(
      `${configuration.apiUrl}/api/v1/admin${path.startsWith("/") ? path : `/${path}`}`,
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
    throw new AdminApiError(
      "The Admin API could not be reached. Check the API address and try again.",
    );
  }
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
export function useAdminQuery<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  const hasData = useRef(false);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      setRefreshing(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    // Only the first fetch for a path is "loading". A refresh keeps the
    // current rows on screen: swapping them for a skeleton would unmount
    // whatever the person is doing — an open upload queue, for instance.
    if (hasData.current) setRefreshing(true);
    else setLoading(true);
    setError(null);
    adminRequest<T>(path, { signal: controller.signal })
      .then((result) => {
        hasData.current = true;
        setData(result);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(describeRequestFailure(caught, "This view"));
        }
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => controller.abort();
  }, [path, revision]);

  // A new path is a different question, so its first answer loads from scratch.
  useEffect(() => {
    hasData.current = false;
  }, [path]);

  return { data, error, loading, refreshing, reload };
}

/** Upload one managed-source file while exposing real browser upload progress. */
export function uploadDatasourceFile<T>(
  connectorId: string,
  file: File,
  options: { onProgress?: (percent: number) => void; signal?: AbortSignal } = {},
): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) {
    return Promise.reject(new AdminApiError(
      `Admin access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
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
    for (const [name, value] of Object.entries(requestIdentityHeaders(configuration))) {
      request.setRequestHeader(name, value);
    }
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

/** Upload one local file directly into a governed collection. */
export function uploadCollectionFile<T>(
  collectionId: string,
  file: File,
  options: {
    idempotencyKey: string;
    onProgress?: (percent: number) => void;
    onProcessing?: () => void;
  },
): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) {
    return Promise.reject(new AdminApiError(
      `Admin access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
    ));
  }

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file, file.name);
    request.open(
      "POST",
      `${configuration.apiUrl}/api/v1/collections/${encodeURIComponent(collectionId)}/documents/upload`,
    );
    request.responseType = "json";
    request.setRequestHeader("Accept", "application/json");
    request.setRequestHeader("Idempotency-Key", options.idempotencyKey);
    for (const [name, value] of Object.entries(requestIdentityHeaders(configuration))) {
      request.setRequestHeader(name, value);
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options.onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.upload.onload = () => options.onProcessing?.();
    request.onerror = () => reject(new AdminApiError(
      `The upload could not reach the ${appBrand.productName} API.`,
    ));
    request.onload = () => {
      const payload = request.response as { detail?: unknown } | T | null;
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as T);
        return;
      }
      const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
        ? payload.detail
        : `Upload failed with status ${request.status}`;
      reject(new AdminApiError(detail, request.status));
    };
    request.send(form);
  });
}

/** Retry indexing from a previously stored native upload. */
export async function retryCollectionDocument<T>(documentId: string): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) {
    throw new AdminApiError(
      `Admin access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
    );
  }
  let response: Response;
  try {
    response = await fetch(
      `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}/retry`,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...requestIdentityHeaders(configuration),
        },
      },
    );
  } catch {
    throw new AdminApiError(
      `The indexing retry could not reach the ${appBrand.productName} API.`,
    );
  }
  const payload = await response.json().catch(() => null) as { detail?: unknown } | T | null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
      ? payload.detail
      : `Indexing retry failed with status ${response.status}`;
    throw new AdminApiError(detail, response.status);
  }
  return payload as T;
}
