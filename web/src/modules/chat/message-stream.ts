import type {
  AgentItem,
  AgentItemStore,
  AgentStreamEvent,
  ChatMessage,
  ChatMessagePart,
} from "./types";
import { upsertStatusPart } from "./stream-parts.ts";

export function emptyItemStore(): AgentItemStore {
  return { items: {}, historyItemIds: [], activeItemIds: [], turnStatus: "idle" };
}

/** Reduce lifecycle events into stable completed history plus mutable active items. */
export function reduceItemEvent(
  current: AgentItemStore,
  event: AgentStreamEvent,
): AgentItemStore {
  if (event.type === "turn.started") return { ...current, turnStatus: "in_progress" };
  if (event.type === "turn.completed") return { ...current, turnStatus: "completed" };
  if (event.type === "error") return { ...current, turnStatus: "failed" };
  if (event.type === "item.delta") {
    const item = current.items[event.item_id];
    if (!item || item.type !== "message" || !item.id) return current;
    return replaceItem(current, {
      ...item,
      content: appendText(item.content, event.delta),
    });
  }
  const item = event.item;
  if (!item.id) return current;
  if (event.type === "item.started") {
    return {
      ...current,
      items: { ...current.items, [item.id]: item },
      activeItemIds: current.activeItemIds.includes(item.id)
        ? current.activeItemIds
        : [...current.activeItemIds, item.id],
    };
  }
  if (event.type === "item.completed") {
    const merged = preserveStreamedMessage(current.items[item.id], item);
    return {
      ...current,
      items: { ...current.items, [item.id]: merged },
      activeItemIds: current.activeItemIds.filter((id) => id !== item.id),
      historyItemIds: current.historyItemIds.includes(item.id)
        ? current.historyItemIds
        : [...current.historyItemIds, item.id],
    };
  }
  return current;
}

export function applyAgentStreamEvent(
  messages: ChatMessage[],
  assistantId: string,
  event: AgentStreamEvent,
): ChatMessage[] {
  return messages.map((message) => {
    if (message.id !== assistantId) return message;
    const runtime = reduceItemEvent(message.runtime ?? emptyItemStore(), event);
    return {
      ...message,
      runtime,
      parts: projectParts(message.parts, runtime, event),
    };
  });
}

function replaceItem(store: AgentItemStore, item: AgentItem): AgentItemStore {
  if (!item.id) return store;
  return { ...store, items: { ...store.items, [item.id]: item } };
}

function preserveStreamedMessage(previous: AgentItem | undefined, item: AgentItem): AgentItem {
  if (
    item.type === "message"
    && previous?.type === "message"
    && !item.content.some((part) => part.text)
  ) {
    return { ...item, content: previous.content };
  }
  return item;
}

function appendText(
  content: Extract<AgentItem, { type: "message" }>["content"],
  delta: string,
) {
  return content.length
    ? content.map((part, index) => index === 0 ? { ...part, text: part.text + delta } : part)
    : [{ type: "output_text" as const, text: delta }];
}

function projectParts(
  existing: ChatMessagePart[],
  runtime: AgentItemStore,
  event: AgentStreamEvent,
): ChatMessagePart[] {
  let parts: ChatMessagePart[] = existing.filter((part) => (
    part.type !== "text"
    && part.type !== "data-status"
    && part.type !== "data-source"
    && part.type !== "data-stream-error"
  ));
  const orderedIds = [...runtime.historyItemIds, ...runtime.activeItemIds.filter(
    (id) => !runtime.historyItemIds.includes(id),
  )];
  for (const id of orderedIds) {
    const item = runtime.items[id];
    if (!item) continue;
    if (item.type === "message" && item.id) {
      const text = item.content.map((part) => part.text).join("");
      if (!text) continue;
      if (
        item.phase === undefined
        || item.phase === "commentary"
        || item.phase === "final_answer"
      ) {
        parts.push({
          type: "text",
          id: item.id,
          text,
          state: item.status === "completed" ? "done" : "streaming",
          phase: item.phase,
        });
      }
    } else if (item.type === "tool_call" && item.id) {
      parts = upsertStatusPart(parts, toolPart(item, runtime.activeItemIds.includes(item.id)));
    } else if (item.type === "tool_result") {
      const call = Object.values(runtime.items).find((candidate) => (
        candidate.type === "tool_call" && candidate.call_id === item.call_id
      ));
      if (call?.type === "tool_call" && call.id) {
        parts = upsertStatusPart(parts, resultPart(call, item));
      }
    } else if (item.type === "evidence" && item.id) {
      parts.push(sourcePart(item));
    }
  }
  if (event.type === "turn.completed") return completeTurn(parts, event);
  if (event.type === "error") {
    return updateRun([...parts, {
      type: "data-stream-error", id: "stream-error",
      data: { message: event.message, retryable: true },
    }], { status: "failed" });
  }
  return parts;
}

function toolPart(
  item: Extract<AgentItem, { type: "tool_call" }>,
  isActive: boolean,
): Extract<ChatMessagePart, { type: "data-status" }> {
  return { type: "data-status", id: item.id, data: {
    phase: item.category === "retrieval" ? "retrieval" : "tool",
    state: isActive ? "active" : item.status === "skipped" ? "skipped" : item.status === "failed" ? "error" : "completed",
    label: item.label ?? displayToolName(item.name), toolName: item.name, toolCallId: item.call_id,
    activityType: item.category === "retrieval" ? "knowledge_retrieval" : "tool_execution", stepId: item.id,
  } };
}

function resultPart(
  call: Extract<AgentItem, { type: "tool_call" }>,
  result: Extract<AgentItem, { type: "tool_result" }>,
): Extract<ChatMessagePart, { type: "data-status" }> {
  return { type: "data-status", id: call.id, data: {
    phase: call.category === "retrieval" ? "retrieval" : "tool",
    state: result.status === "completed" ? "completed" : result.status === "skipped" ? "skipped" : "error",
    label: call.label ?? displayToolName(call.name), detail: result.error ?? undefined,
    toolName: call.name, toolCallId: call.call_id, durationMs: result.duration_ms ?? undefined,
    resultCount: result.result_count ?? undefined,
    activityType: call.category === "retrieval" ? "knowledge_retrieval" : "tool_execution", stepId: call.id,
  } };
}

type RunPart = Extract<ChatMessagePart, { type: "data-run" }>;

function completeTurn(parts: ChatMessagePart[], event: Extract<AgentStreamEvent, { type: "turn.completed" }>) {
  const metrics: Partial<RunPart["data"]> = { status: "completed" };
  if (event.duration_ms != null) metrics.durationMs = event.duration_ms;
  if (event.model_duration_ms != null) metrics.modelDurationMs = event.model_duration_ms;
  if (event.tool_duration_ms != null) metrics.toolDurationMs = event.tool_duration_ms;
  if (event.tool_call_count != null) metrics.toolCallCount = event.tool_call_count;
  return updateRun(parts, metrics);
}

export function updateRun(parts: ChatMessagePart[], patch: Partial<RunPart["data"]>): ChatMessagePart[] {
  const index = parts.findIndex((part) => part.type === "data-run");
  if (index === -1) return [...parts, { type: "data-run", id: "run", data: { status: "running", startedAt: Date.now(), ...patch } }];
  const current = parts[index] as RunPart;
  return [...parts.slice(0, index), { ...current, data: { ...current.data, ...patch } }, ...parts.slice(index + 1)];
}

function displayToolName(toolName: string) {
  return toolName.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sourcePart(evidence: Extract<AgentItem, { type: "evidence" }>): Extract<ChatMessagePart, { type: "data-source" }> {
  return { type: "data-source", id: evidence.id, data: {
    id: evidence.id, title: evidence.title, url: evidence.uri ?? undefined,
    description: evidence.section ?? evidence.page ?? undefined, page: evidence.page ?? undefined,
    section: evidence.section ?? undefined, snippet: evidence.snippet ?? undefined,
    status: evidence.status === "used" ? "Used" : "Found", source: evidence.source ?? undefined,
    relevanceScore: evidence.relevance_score ?? undefined,
  } };
}
