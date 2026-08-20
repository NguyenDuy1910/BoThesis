import type { AgentItemStore, ChatMessagePart } from "./types";

export type AssistantTurnItem =
  | {
      kind: "message";
      id: string;
      text: string;
      state: "streaming" | "done";
    }
  | {
      kind: "tool";
      id: string;
      label: string;
      detail?: string;
      category: "document" | "retrieval" | "tool";
      state: "active" | "completed" | "error" | "skipped";
      count: number;
    }
  | {
      kind: "response";
      id: string;
      text: string;
      state: "streaming" | "done";
    };

export function assistantTurnItems(
  parts: ChatMessagePart[],
  isStreaming: boolean,
  runtime?: AgentItemStore,
): AssistantTurnItem[] {
  if (runtime) return runtimeItems(runtime);
  const items: AssistantTurnItem[] = [];
  for (const [index, part] of parts.entries()) {
    if (part.type === "data-status") {
      const category = inlineToolCategory(part);
      if (!category) continue;
      const label = cleanActivityLabel(part.data.label, part.data.toolName);
      const id = part.data.stepId ?? part.id ?? `tool-${index}`;
      const existingIndex = items.findIndex((item) => item.kind === "tool" && item.id === id);
      const next = {
        kind: "tool",
        id,
        label,
        detail: part.data.detail?.trim() || undefined,
        category,
        state: part.data.state,
        count: 1,
      } as const;
      if (existingIndex === -1) {
        items.push(next);
      } else {
        const existing = items[existingIndex] as Extract<AssistantTurnItem, { kind: "tool" }>;
        items[existingIndex] = {
          ...next,
          id: existing.id,
          count: existing.count + 1,
          detail: next.detail ?? existing.detail,
        };
      }
      continue;
    }

    if (part.type === "text" && part.text) {
      if (part.phase === "commentary") {
        items.push({ kind: "message", id: part.id ?? `message-${index}`, text: part.text, state: part.state });
      } else {
        items.push({
          kind: "response",
          id: part.id ?? `response-${index}`,
          text: part.text,
          state: part.state,
        });
      }
    }
  }

  return items;
}

function runtimeItems(runtime: AgentItemStore): AssistantTurnItem[] {
  const items: AssistantTurnItem[] = [];
  const orderedIds = [...runtime.historyItemIds, ...runtime.activeItemIds.filter(
    (id) => !runtime.historyItemIds.includes(id),
  )];
  for (const id of orderedIds) {
    const item = runtime.items[id];
    if (!item) continue;
    if (item.type === "message" && item.id) {
      const text = item.content.map((part) => part.text).join("");
      if (!text) continue;
      if (item.phase === "commentary") {
        items.push({
          kind: "message",
          id: item.id,
          text,
          state: item.status === "completed" ? "done" : "streaming",
        });
      } else if (item.phase === undefined || item.phase === "final_answer") {
        items.push({
          kind: "response",
          id: item.id,
          text,
          state: item.status === "completed" ? "done" : "streaming",
        });
      }
      continue;
    }
    if (item.type !== "tool_call" || !item.id) continue;
    const result = Object.values(runtime.items).find((candidate) => (
      candidate.type === "tool_result" && candidate.call_id === item.call_id
    ));
    const active = runtime.activeItemIds.includes(item.id);
    const state = result?.type === "tool_result"
      ? result.status === "completed" ? "completed" : result.status === "skipped" ? "skipped" : "error"
      : active ? "active" : item.status === "skipped" ? "skipped" : item.status === "failed" ? "error" : "completed";
    items.push({
      kind: "tool",
      id: item.id,
      label: cleanActivityLabel(item.label ?? "", item.name),
      detail: result?.type === "tool_result" ? result.error ?? undefined : undefined,
      category: item.category,
      state,
      count: 1,
    });
  }
  return items;
}

function inlineToolCategory(
  part: Extract<ChatMessagePart, { type: "data-status" }>,
): "document" | "retrieval" | "tool" | undefined {
  if (part.data.phase === "document" || part.data.activityType === "document_preparation") {
    return "document";
  }
  if (part.data.phase === "retrieval" || part.data.activityType === "knowledge_retrieval") {
    return "retrieval";
  }
  if (part.data.phase === "tool" || part.data.activityType === "tool_execution") {
    return "tool";
  }
  return undefined;
}

function cleanActivityLabel(label: string, toolName: string | undefined) {
  const cleanLabel = label
    .replace(/^(?:Act|Observe)\s*[·:]\s*/i, "")
    .trim();
  if (cleanLabel && !/^(?:Think|Final response)$/i.test(cleanLabel)) {
    return cleanLabel;
  }
  if (!toolName) return "Using tool";
  return toolName
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
