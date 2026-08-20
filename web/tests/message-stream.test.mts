import assert from "node:assert/strict";
import test from "node:test";

import { applyAgentStreamEvent } from "../src/modules/chat/message-stream.ts";
import type { ChatMessage } from "../src/modules/chat/types.ts";

test("materializes the final response from generic message item lifecycle events", () => {
  const assistantId = "assistant-1";
  let messages: ChatMessage[] = [assistantPlaceholder(assistantId)];
  const item = {
    type: "message" as const, id: "msg-1", role: "assistant" as const,
    phase: "final_answer" as const, status: "in_progress" as const,
    content: [{ type: "output_text" as const, text: "" }],
  };

  messages = applyAgentStreamEvent(messages, assistantId, { type: "turn.started" });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.started", item });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.delta", item_id: "msg-1", delta: "Grounded " });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.delta", item_id: "msg-1", delta: "answer." });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.completed", item: { ...item, status: "completed" } });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "turn.completed" });

  assert.deepEqual(messages[0].parts, [
    { type: "data-run", id: "run", data: { status: "completed", startedAt: 1 } },
    {
      type: "text",
      id: "msg-1",
      text: "Grounded answer.",
      state: "done",
      phase: "final_answer",
    },
  ]);
  assert.equal(messages[0].runtime?.items["msg-1"]?.type, "message");
  assert.deepEqual(messages[0].runtime?.activeItemIds, []);
  assert.deepEqual(messages[0].runtime?.historyItemIds, ["msg-1"]);
});

test("keeps a commentary item active until completion and preserves ordered history", () => {
  const assistantId = "assistant-1";
  let messages: ChatMessage[] = [assistantPlaceholder(assistantId)];
  const commentary = {
    type: "message" as const, id: "commentary-1", role: "assistant" as const,
    phase: "commentary" as const, status: "in_progress" as const,
    content: [{ type: "output_text" as const, text: "" }],
  };
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.started", item: commentary });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.delta", item_id: "commentary-1", delta: "Checking the policy." });
  assert.deepEqual(messages[0].runtime?.activeItemIds, ["commentary-1"]);
  assert.deepEqual(messages[0].parts.at(-1), {
    type: "text",
    id: "commentary-1",
    text: "Checking the policy.",
    state: "streaming",
    phase: "commentary",
  });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.completed", item: { ...commentary, status: "completed" } });
  assert.deepEqual(messages[0].runtime?.activeItemIds, []);
  assert.deepEqual(messages[0].runtime?.historyItemIds, ["commentary-1"]);
});

test("updates a tool activity from tool-call and tool-result item state", () => {
  const assistantId = "assistant-1";
  let messages: ChatMessage[] = [assistantPlaceholder(assistantId)];
  const call = {
    type: "tool_call" as const, id: "tool-1", call_id: "call-1", name: "knowledge_search",
    label: "Search knowledge base", category: "retrieval" as const, status: "in_progress" as const,
  };
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.started", item: call });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.started", item: {
    type: "tool_result", id: "tool-1:result", call_id: "call-1", name: "knowledge_search", status: "in_progress",
  } });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.completed", item: {
    type: "tool_result", id: "tool-1:result", call_id: "call-1", name: "knowledge_search", status: "completed", result_count: 2,
  } });
  messages = applyAgentStreamEvent(messages, assistantId, { type: "item.completed", item: { ...call, status: "completed" } });

  const status = messages[0].parts.find((part) => part.type === "data-status");
  assert.equal(status?.type === "data-status" ? status.data.state : undefined, "completed");
  assert.equal(status?.type === "data-status" ? status.data.resultCount : undefined, 2);
});

function assistantPlaceholder(id: string): ChatMessage {
  return { id, role: "assistant", parts: [{ type: "data-run", id: "run", data: { status: "running", startedAt: 1 } }] };
}
