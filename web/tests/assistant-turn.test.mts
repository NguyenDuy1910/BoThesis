import assert from "node:assert/strict";
import test from "node:test";

import { assistantTurnItems } from "../src/modules/chat/assistant-turn.ts";
import { upsertStatusPart } from "../src/modules/chat/stream-parts.ts";
import type { ChatMessagePart } from "../src/modules/chat/types.ts";

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
  ]);

  assert.deepEqual(items, [{
    kind: "response",
    id: "response-2",
    text: "The answer.",
    state: "streaming",
  }]);
});

test("preserves arbitrary interim, parallel tool, and final ordering", () => {
  const parts: ChatMessagePart[] = [
    {
      type: "data-reasoning",
      id: "interim-0",
      data: {
        source: "model",
        turn: 0,
        text: "I’ll check Core TM first.",
        state: "done",
      },
    },
    toolPart("core", "Search Knowledge", "completed"),
    toolPart("product", "Search product configuration", "completed"),
    {
      type: "data-reasoning",
      id: "interim-1",
      data: {
        source: "model",
        turn: 1,
        text: "The result is incomplete, so I’ll narrow the search.",
        state: "done",
      },
    },
    toolPart("lending", "Search lending configuration", "completed"),
    { type: "text", text: "Grounded final answer.", state: "done" },
  ];

  assert.deepEqual(
    assistantTurnItems(parts).map((item) => (
      item.kind === "interim" ? item.text : item.kind === "tool" ? item.label : item.text
    )),
    [
      "I’ll check Core TM first.",
      "Search Knowledge",
      "Search product configuration",
      "The result is incomplete, so I’ll narrow the search.",
      "Search lending configuration",
      "Grounded final answer.",
    ],
  );
});

test("tool completion updates the existing ordered row", () => {
  const started = toolPart("search-1", "Act · Search Knowledge", "active");
  const completed = toolPart("search-1", "Observe · Search Knowledge", "completed");
  const withStart = upsertStatusPart([], started);
  const withCompletion = upsertStatusPart(withStart, completed);
  const items = assistantTurnItems(withCompletion);

  assert.equal(withCompletion.length, 1);
  assert.deepEqual(items, [{
    kind: "tool",
    id: "tool-search-1",
    label: "Search Knowledge",
    category: "retrieval",
    state: "completed",
    detail: undefined,
  }]);
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
