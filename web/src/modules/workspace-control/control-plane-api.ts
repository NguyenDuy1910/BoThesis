"use client";

import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import { describeRequestFailure } from "@/lib/api/errors";
import { ApiError, apiRequest } from "@/lib/api/request";
import { appBrand } from "@/lib/brand";
import { useCallback, useEffect, useRef, useState } from "react";

/** Error type for workspace-control requests. */
export class ControlPlaneApiError extends ApiError {
  constructor(message: string, status?: number) {
    super(message, status);
    this.name = "ControlPlaneApiError";
  }
}

/** Request boundary shared by workspace and platform control surfaces. */
export async function controlPlaneRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  try {
    return await apiRequest<T>(path.startsWith("/") ? path : `/${path}`, init);
  } catch (cause) {
    if (cause instanceof ApiError && !(cause instanceof ControlPlaneApiError)) {
      throw new ControlPlaneApiError(cause.message, cause.status);
    }
    throw cause;
  }
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
 * Shared request state for control-plane views. Keeping this next to the
 * request boundary gives every control surface the same cancellation
 * and retry behaviour without duplicating fetch effects.
 */
export function useControlPlaneQuery<T>(path: string | null) {
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
    controlPlaneRequest<T>(path, { signal: controller.signal })
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
    return Promise.reject(new ControlPlaneApiError(
      `Workspace access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
    ));
  }

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file, file.name);
    request.open(
      "POST",
      `${configuration.apiUrl}/api/v1/collections/${encodeURIComponent(collectionId)}/documents`,
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
    request.onerror = () => reject(new ControlPlaneApiError(
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
      reject(new ControlPlaneApiError(detail, request.status));
    };
    request.send(form);
  });
}

/** Retry indexing from a previously stored native upload. */
export async function retryCollectionDocument<T>(documentId: string): Promise<T> {
  const configuration = getApiConfiguration();
  if (!configuration) {
    throw new ControlPlaneApiError(
      `Workspace access is not configured. Set the ${appBrand.productName} API, tenant, and user environment values.`,
    );
  }
  let response: Response;
  try {
    response = await fetch(
      `${configuration.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}/content`,
      {
        method: "PUT",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...requestIdentityHeaders(configuration),
        },
      },
    );
  } catch {
    throw new ControlPlaneApiError(
      `The indexing retry could not reach the ${appBrand.productName} API.`,
    );
  }
  const payload = await response.json().catch(() => null) as { detail?: unknown } | T | null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string"
      ? payload.detail
      : `Indexing retry failed with status ${response.status}`;
    throw new ControlPlaneApiError(detail, response.status);
  }
  return payload as T;
}
