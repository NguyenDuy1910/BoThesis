import assert from "node:assert/strict";
import test from "node:test";

import { assistantTurnItems } from "../src/modules/chat/assistant-turn.ts";
import type { TurnState } from "../src/modules/chat/types.ts";

test("renders message items directly from semantic item state", () => {
  const items = assistantTurnItems(turnWithFinalMessage());

  assert.deepEqual(items, [{
    kind: "message",
    id: "message-1",
    text: "The answer.",
    state: "done",
  }]);
});

test("keeps interleaved response item ordering and completes tools when a later response starts", () => {
  const turn: TurnState = {
    id: "turn-1",
    status: "streaming",
    responseOrder: ["response-1", "response-2"],
    responses: {
      "response-1": {
        id: "response-1", status: "completed", itemOrder: ["message-1", "tool-1"],
        items: {
          "message-1": {
            type: "message", id: "message-1", role: "assistant", status: "completed",
            content: [{ type: "output_text", text: "I’ll check the policy.", annotations: [] }],
          },
          "tool-1": {
            type: "function_call", id: "tool-1", call_id: "call-1", name: "knowledge_search",
            arguments: "{}", status: "completed",
          },
        },
      },
      "response-2": {
        id: "response-2", status: "in_progress", itemOrder: ["message-2"],
        items: {
          "message-2": {
            type: "message", id: "message-2", role: "assistant", status: "in_progress",
            content: [{ type: "output_text", text: "Grounded answer.", annotations: [] }],
          },
        },
      },
    },
  };

  assert.deepEqual(
    assistantTurnItems(turn).map((item) => [item.kind, item.kind === "tool" ? item.state : item.id]),
    [["message", "message-1"], ["tool", "completed"], ["message", "message-2"]],
  );
});

test("keeps the newest function call active while its enclosing Turn continues", () => {
  const turn: TurnState = {
    id: "turn-1",
    status: "streaming",
    responseOrder: ["response-1"],
    responses: {
      "response-1": {
        id: "response-1", status: "completed", itemOrder: ["tool-1"],
        items: {
          "tool-1": {
            type: "function_call", id: "tool-1", call_id: "call-1", name: "sql_query",
            arguments: "{}", status: "completed",
          },
        },
      },
    },
  };

  assert.deepEqual(assistantTurnItems(turn), [{
    kind: "tool", id: "tool-1", name: "sql_query", state: "active",
  }]);
});

test("renders provider reasoning summaries as a collapsed semantic activity", () => {
  const turn = turnWithFinalMessage();
  turn.responses["response-1"]!.itemOrder.unshift("reasoning-1");
  turn.responses["response-1"]!.items["reasoning-1"] = {
    type: "reasoning", id: "reasoning-1", status: "completed",
    summary: [{ type: "summary_text", text: "I should verify the policy source." }],
  };

  const [reasoning] = assistantTurnItems(turn);
  assert.deepEqual(reasoning, {
    kind: "reasoning",
    id: "reasoning-1",
    text: "I should verify the policy source.",
    state: "completed",
  });
});

function turnWithFinalMessage(): TurnState {
  return {
    id: "turn-1",
    status: "completed",
    responseOrder: ["response-1"],
    responses: {
      "response-1": {
        id: "response-1", status: "completed", itemOrder: ["message-1"],
        items: {
          "message-1": {
            type: "message", id: "message-1", role: "assistant", status: "completed",
            content: [{ type: "output_text", text: "The answer.", annotations: [] }],
          },
        },
      },
    },
  };
}
