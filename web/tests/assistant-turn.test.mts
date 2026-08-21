import assert from "node:assert/strict";
import test from "node:test";

import { assistantTurnItems } from "../src/modules/chat/assistant-turn.ts";
import { upsertStatusPart } from "../src/modules/chat/stream-parts.ts";
import type { AgentItemStore, ChatMessagePart } from "../src/modules/chat/types.ts";

test("renders a direct final response without synthetic progress concepts", () => {
  const items = assistantTurnItems([
    { type: "data-run", data: { status: "running", startedAt: 1 } },
    {
      type: "data-status",
      id: "generation-0",
      data: {
        phase: "model",
        state: "completed",
        label: "Final response",
        activityType: "final_response_generation",
      },
    },
    { type: "text", text: "The answer.", state: "streaming" },
  ], true);

  assert.deepEqual(items, [{
    kind: "response",
    id: "response-2",
    text: "The answer.",
    state: "streaming",
  }]);
});

test("renders interleaved commentary, tool activity, and the final answer from item state", () => {
  const runtime: AgentItemStore = {
    turnStatus: "in_progress",
    activeItemIds: [],
    historyItemIds: ["commentary-1", "tool-1", "response-1"],
    items: {
      "commentary-1": {
        type: "message", id: "commentary-1", role: "assistant", phase: "commentary",
        status: "completed", content: [{ type: "output_text", text: "Checking the policy." }],
      },
      "tool-1": {
        type: "tool_call", id: "tool-1", call_id: "call-1", name: "knowledge_search",
        label: "Search knowledge base", category: "retrieval", status: "completed",
      },
      "response-1": {
        type: "message", id: "response-1", role: "assistant", phase: "final_answer",
        status: "in_progress", content: [{ type: "output_text", text: "Grounded answer." }],
      },
    },
  };

  assert.deepEqual(
    assistantTurnItems([], true, runtime).map((item) => item.kind),
    ["message", "tool", "response"],
  );
});

test("tool completion updates the existing ordered row", () => {
  const started = toolPart("search-1", "Act · Search Knowledge", "active");
  const completed = toolPart("search-1", "Observe · Search Knowledge", "completed");
  const withStart = upsertStatusPart([], started);
  const withCompletion = upsertStatusPart(withStart, completed);
  const items = assistantTurnItems(withCompletion, true);

  assert.equal(withCompletion.length, 1);
  assert.deepEqual(items, [{
    kind: "tool",
    id: "tool-search-1",
    label: "Search Knowledge",
    category: "retrieval",
    state: "completed",
    detail: undefined,
    resultCount: undefined,
    durationMs: undefined,
  }]);
});

test("tool rows carry the result count and duration the stream reported", () => {
  const completed = toolPart("search-2", "Observe · Search Knowledge", "completed");
  completed.data.resultCount = 12;
  completed.data.durationMs = 1420;
  const [item] = assistantTurnItems([completed], false);

  assert.equal(item?.kind, "tool");
  assert.equal(item?.kind === "tool" && item.resultCount, 12);
  assert.equal(item?.kind === "tool" && item.durationMs, 1420);
});

function toolPart(
  id: string,
  label: string,
  state: "active" | "completed" | "error" | "skipped",
): Extract<ChatMessagePart, { type: "data-status" }> {
  return {
    type: "data-status",
    id: `tool-${id}`,
    data: {
      phase: "retrieval",
      state,
      label,
      activityType: "knowledge_retrieval",
      stepId: `tool-${id}`,
      toolCallId: id,
    },
  };
}
