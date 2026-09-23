import { getApiConfiguration, requestIdentityHeaders } from "@/lib/api/config";
import type {
  KnowledgeCitationResponse,
  KnowledgeItemViewer,
} from "./types";

/** A viewer request failed before any source content was exposed. */
export class KnowledgeViewerRequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function getKnowledgeItemViewer(
  itemId: string,
  chunkId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeItemViewer> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const query = chunkId ? `?chunk=${encodeURIComponent(chunkId)}` : "";
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/documents/${encodeURIComponent(itemId)}${query}`,
    {
      cache: "no-store",
      headers: requestIdentityHeaders(configuration),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new KnowledgeViewerRequestError(
      response.status,
      detail || `Could not open this knowledge item (${response.status}).`,
    );
  }
  return await response.json() as KnowledgeItemViewer;
}

export async function getKnowledgeCitation(
  itemId: string,
  chunkId: string,
  signal?: AbortSignal,
): Promise<KnowledgeCitationResponse> {
  const configuration = getApiConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/documents/${encodeURIComponent(itemId)}/citations/${encodeURIComponent(chunkId)}`,
    {
      cache: "no-store",
      headers: requestIdentityHeaders(configuration),
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Could not resolve this citation (${response.status}).`);
  }
  return await response.json() as KnowledgeCitationResponse;
}
