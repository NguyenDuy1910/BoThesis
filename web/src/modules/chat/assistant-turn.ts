import type { AgentItem, AgentItemStore, ChatMessagePart } from "./types";

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
      resultCount?: number;
      durationMs?: number;
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
      // ``upsertStatusPart`` keeps exactly one status part per step, so each
      // step is seen once here and needs no de-duplication.
      items.push({
        kind: "tool",
        id: part.data.stepId ?? part.id ?? `tool-${index}`,
        label: cleanActivityLabel(part.data.label, part.data.toolName),
        detail: part.data.detail?.trim() || undefined,
        category,
        state: part.data.state,
        resultCount: part.data.resultCount,
        durationMs: part.data.durationMs,
      });
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
  const resultsByCallId = new Map<string, Extract<AgentItem, { type: "tool_result" }>>();
  for (const candidate of Object.values(runtime.items)) {
    if (candidate.type === "tool_result") resultsByCallId.set(candidate.call_id, candidate);
  }

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
    const result = resultsByCallId.get(item.call_id);
    const active = runtime.activeItemIds.includes(item.id);
    const state = result
      ? result.status === "completed" ? "completed" : result.status === "skipped" ? "skipped" : "error"
      : active ? "active" : item.status === "skipped" ? "skipped" : item.status === "failed" ? "error" : "completed";
    items.push({
      kind: "tool",
      id: item.id,
      label: cleanActivityLabel(item.label ?? "", item.name),
      detail: result?.error ?? undefined,
      category: item.category,
      state,
      resultCount: result?.result_count ?? undefined,
      durationMs: result?.duration_ms ?? undefined,
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
