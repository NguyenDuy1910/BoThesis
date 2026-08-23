import { getBothesisChatConfiguration } from "@/lib/api/config";
import type { KnowledgeCitationResponse, KnowledgeItemViewer } from "./types";

export async function getKnowledgeItemViewer(
  itemId: string,
  chunkId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeItemViewer> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const query = chunkId ? `?chunk=${encodeURIComponent(chunkId)}` : "";
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/items/${encodeURIComponent(itemId)}${query}`,
    {
      cache: "no-store",
      headers: {
        "X-Bothesis-User-Id": configuration.userId,
        "X-Bothesis-Tenant-Id": configuration.tenantId,
      },
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Could not open this knowledge item (${response.status}).`);
  }
  return await response.json() as KnowledgeItemViewer;
}

export async function getKnowledgeCitation(
  itemId: string,
  chunkId: string,
  signal?: AbortSignal,
): Promise<KnowledgeCitationResponse> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new Error("Knowledge viewer is not configured.");
  const response = await fetch(
    `${configuration.apiUrl}/api/v1/knowledge/items/${encodeURIComponent(itemId)}/citations/${encodeURIComponent(chunkId)}`,
    {
      cache: "no-store",
      headers: {
        "X-Bothesis-User-Id": configuration.userId,
        "X-Bothesis-Tenant-Id": configuration.tenantId,
      },
      signal,
    },
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Could not resolve this citation (${response.status}).`);
  }
  return await response.json() as KnowledgeCitationResponse;
}
