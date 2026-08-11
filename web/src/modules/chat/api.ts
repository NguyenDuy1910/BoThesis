import { getBothesisChatConfiguration } from "@/lib/api/config";
import { StreamEventDeduplicator } from "./stream-deduplicator";
import type { AgentHistoryMessage, AgentStreamEvent } from "./types";

export class ChatConfigurationError extends Error {
  constructor() {
    super(
      "Chat is not configured. Set NEXT_PUBLIC_BOTHESIS_API_URL, NEXT_PUBLIC_BOTHESIS_TENANT_ID, NEXT_PUBLIC_BOTHESIS_USER_ID, and NEXT_PUBLIC_BOTHESIS_ROLES."
    );
  }
}

export async function streamAgentResponse(
  message: string,
  options: {
    conversationId?: string | null;
    history: AgentHistoryMessage[];
    signal: AbortSignal;
    onEvent: (event: AgentStreamEvent) => void;
  }
): Promise<void> {
  const configuration = getBothesisChatConfiguration();
  if (!configuration) throw new ChatConfigurationError();

  const response = await fetch(`${configuration.apiUrl}/api/v1/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({
      message,
      tenant_id: configuration.tenantId,
      user_id: configuration.userId,
      roles: configuration.roles,
      conversation_id: options.conversationId ?? null,
      history: options.history,
    }),
  });
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    throw new Error(detail || `Chat request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const deduplicator = new StreamEventDeduplicator();

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop() ?? "";

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        const event = JSON.parse(payload) as AgentStreamEvent;
        if (!deduplicator.shouldAccept(event)) continue;
        options.onEvent(event);
      } catch {
        throw new Error("Received an invalid agent stream event.");
      }
    }
    if (done) break;
  }
}
