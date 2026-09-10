import assert from "node:assert/strict";
import test from "node:test";

import { assistantTurnItems } from "../src/modules/chat/assistant-turn.ts";
import type { TurnState } from "../src/modules/chat/types.ts";

test("renders message items directly from semantic item state", () => {
  const items = assistantTurnItems(turnWithFinalMessage());

  assert.deepEqual(items, [{
    kind: "message",
    id: "message-1",
    phase: "final_answer",
    text: "The answer.",
    state: "done",
  }]);
});

test("does not present a model function call as runtime activity", () => {
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
    [["message", "message-1"], ["message", "message-2"]],
  );
});

test("presents a verified runtime activity at its function-call position", () => {
  const turn: TurnState = {
    id: "turn-1",
    status: "streaming",
    responseOrder: ["response-1"],
    runtimeActivities: [{
      callId: "call-1", toolName: "sql_query", state: "active", startedAt: 1,
    }],
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
    kind: "activity", id: "call-1",
    activity: { callId: "call-1", toolName: "sql_query", state: "active", startedAt: 1 },
  }]);
});

test("presents hosted shell execution with its command and captured output", () => {
  const turn: TurnState = {
    id: "turn-1",
    status: "streaming",
    responseOrder: ["response-1"],
    responses: {
      "response-1": {
        id: "response-1", status: "in_progress", itemOrder: ["run-1", "run-2"],
        items: {
          "run-1": {
            type: "hosted_execution_result", id: "run-1", call_id: "shell-1",
            status: "completed", commands: ["printf verified"],
            output: [{ stdout: "verified", stderr: "", exit_code: 0, timed_out: false }],
            workspace_files: ["analysis.csv"],
          },
          "run-2": { type: "hosted_execution_call", id: "run-2", call_id: "shell-2", status: "in_progress", commands: ["date"] },
        },
      },
    },
  };

  assert.deepEqual(assistantTurnItems(turn), [
    {
      kind: "execution", id: "run-1", callId: "shell-1", state: "completed",
      commands: ["printf verified"],
      output: [{ stdout: "verified", stderr: "", exit_code: 0, timed_out: false }],
      files: ["analysis.csv"],
    },
    {
      kind: "execution", id: "run-2", callId: "shell-2", state: "running",
      commands: ["date"], output: [], files: [],
    },
  ]);
});

test("does not render provider reasoning as user-facing commentary", () => {
  const turn = turnWithFinalMessage();
  turn.responses["response-1"]!.itemOrder.unshift("reasoning-1");
  turn.responses["response-1"]!.items["reasoning-1"] = {
    type: "reasoning", id: "reasoning-1", status: "completed",
    summary: [{ type: "summary_text", text: "I should verify the policy source." }],
  };

  assert.deepEqual(assistantTurnItems(turn), [{
    kind: "message",
    id: "message-1",
    phase: "final_answer",
    text: "The answer.",
    state: "done",
  }]);
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
