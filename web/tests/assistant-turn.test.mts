import assert from "node:assert/strict";
import test from "node:test";

import { assistantTurnItems, groupAssistantTurnItems } from "../src/modules/chat/assistant-turn.ts";
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

test("groups every runtime activity into one surface while preserving commentary", () => {
  const grouped = groupAssistantTurnItems([
    {
      kind: "message" as const,
      id: "commentary-1",
      phase: "commentary" as const,
      text: "I found the current policy.",
      state: "done" as const,
    },
    {
      kind: "activity" as const,
      id: "search-1",
      activity: { callId: "search-1", toolName: "knowledge_search", state: "completed" as const, startedAt: 1, resultCount: 2 },
    },
    {
      kind: "activity" as const,
      id: "read-1",
      activity: { callId: "read-1", toolName: "read_resource", state: "active" as const, startedAt: 2 },
    },
    {
      kind: "message" as const,
      id: "commentary-2",
      phase: "commentary" as const,
      text: "I am checking the related guidance.",
      state: "done" as const,
    },
    {
      kind: "activity" as const,
      id: "inspect-1",
      activity: { callId: "inspect-1", toolName: "inspect_resource", state: "active" as const, startedAt: 3 },
    },
    {
      kind: "message" as const,
      id: "answer-1",
      phase: "final_answer" as const,
      text: "The allowance is unchanged.",
      state: "streaming" as const,
    },
  ]);

  assert.deepEqual(grouped.map((item) => item.kind), [
    "message",
    "activity_group",
    "message",
    "message",
  ]);
  assert.equal(grouped[1]?.kind === "activity_group" && grouped[1].activities.length, 3);
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
