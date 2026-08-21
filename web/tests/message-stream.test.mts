import assert from "node:assert/strict";
import test from "node:test";

import {
  applyResponseStreamEvent,
  emptyTurnState,
  finalTurnText,
  reduceResponseStreamEvent,
} from "../src/modules/chat/message-stream.ts";
import { DOCUMENT_CITATION_TYPE } from "../src/modules/chat/types.ts";
import type { ChatMessage, OutputItem, TurnState } from "../src/modules/chat/types.ts";

test("materializes text deltas and annotations into one stable message item", () => {
  const assistantId = "assistant-1";
  let messages: ChatMessage[] = [assistantPlaceholder(assistantId)];
  const response = { id: "response-1", status: "in_progress" as const, output: [] };
  const message: OutputItem = {
    type: "message",
    id: "message-1",
    role: "assistant",
    status: "in_progress",
    content: [{ type: "output_text", text: "", annotations: [] }],
  };

  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.created", response,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.added", output_index: 0, item: message,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.content_part.added", item_id: "message-1",
    output_index: 0, content_index: 0, part: { type: "output_text", text: "", annotations: [] },
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.delta", item_id: "message-1",
    output_index: 0, content_index: 0, delta: "Grounded ",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.annotation.added", item_id: "message-1",
    output_index: 0, content_index: 0,
    annotation: {
      type: DOCUMENT_CITATION_TYPE,
      start_index: 9,
      end_index: 9,
      citation: { id: "source-1", title: "Access Policy", uri: "https://kb/source-1" },
    },
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.delta", item_id: "message-1",
    output_index: 0, content_index: 0, delta: "answer.",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.done", output_index: 0,
    item: { ...message, status: "completed", content: [{ type: "output_text", text: "", annotations: [] }] },
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.completed",
    response: {
      ...response,
      status: "completed",
      output: [{ ...message, status: "completed", content: [{ type: "output_text", text: "", annotations: [] }] }],
    },
  });

  const turn = messages[0]?.turn;
  const item = turn?.responses[response.id]?.items["message-1"];
  assert.equal(turn?.status, "completed");
  assert.equal(item?.type, "message");
  assert.equal(item?.type === "message" && item.content[0]?.type === "output_text" && item.content[0].text, "Grounded answer.");
  assert.equal(item?.type === "message" && item.content[0]?.type === "output_text" && item.content[0].annotations.length, 1);
  assert.deepEqual(messages[0]?.parts, []);
});

test("response completion leaves a Turn streaming when it contains function calls", () => {
  const assistantId = "assistant-1";
  let messages: ChatMessage[] = [assistantPlaceholder(assistantId)];
  const response = { id: "response-1", status: "in_progress" as const, output: [] };
  const functionCall: OutputItem = {
    type: "function_call",
    id: "call-item-1",
    call_id: "call-1",
    name: "knowledge_search",
    arguments: "",
    status: "in_progress",
  };

  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.created", response,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.added", output_index: 0, item: functionCall,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.function_call_arguments.delta", item_id: "call-item-1",
    output_index: 0, delta: "{\"query\":\"policy",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.function_call_arguments.done", item_id: "call-item-1",
    output_index: 0, arguments: "{\"query\":\"policy\"}",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.completed",
    response: { ...response, status: "completed", output: [{ ...functionCall, arguments: "{\"query\":\"policy\"}", status: "completed" }] },
  });

  const turn = messages[0]?.turn;
  assert.equal(turn?.responses[response.id]?.status, "completed");
  assert.equal(turn?.status, "streaming");
  assert.equal(
    turn?.responses[response.id]?.items["call-item-1"]?.type === "function_call"
      && turn.responses[response.id]?.items["call-item-1"]?.arguments,
    "{\"query\":\"policy\"}",
  );
});

test("item events are routed to the response the stream most recently opened", () => {
  // No item-level event carries a response id: the specification identifies the
  // response being mutated by the lifecycle events that bracket it.
  let turn = emptyTurnState("turn-1");
  for (const event of [
    { type: "response.created" as const, response: envelope("response-1") },
    {
      type: "response.output_text.delta" as const,
      item_id: "message-1",
      output_index: 0,
      content_index: 0,
      delta: "Checking.",
    },
    {
      type: "response.completed" as const,
      response: { ...envelope("response-1"), status: "completed" as const },
    },
    {
      type: "response.created" as const,
      response: { ...envelope("response-2"), previous_response_id: "response-1" },
    },
    {
      type: "response.output_text.delta" as const,
      item_id: "message-2",
      output_index: 0,
      content_index: 0,
      delta: "The answer.",
    },
    {
      type: "response.completed" as const,
      response: { ...envelope("response-2"), status: "completed" as const },
    },
  ]) {
    turn = reduceResponseStreamEvent(turn, event);
  }

  assert.deepEqual(turn.responseOrder, ["response-1", "response-2"]);
  assert.equal(turn.responses["response-2"]?.previousResponseId, "response-1");
  assert.equal(textOf(turn, "response-1", "message-1"), "Checking.");
  assert.equal(textOf(turn, "response-2", "message-2"), "The answer.");
});

test("a reasoning item is materialized from its summary and content deltas", () => {
  let turn = emptyTurnState("turn-1");
  for (const event of [
    { type: "response.created" as const, response: envelope("response-1") },
    {
      type: "response.output_item.added" as const,
      output_index: 0,
      item: { type: "reasoning" as const, id: "rs-1", status: "in_progress" as const, summary: [] },
    },
    {
      type: "response.reasoning_summary_text.delta" as const,
      item_id: "rs-1",
      output_index: 0,
      summary_index: 0,
      delta: "check the policy",
    },
    {
      type: "response.reasoning.delta" as const,
      item_id: "rs-1",
      output_index: 0,
      content_index: 0,
      delta: "raw thought",
    },
  ]) {
    turn = reduceResponseStreamEvent(turn, event);
  }
  const item = turn.responses["response-1"]?.items["rs-1"];

  assert.equal(item?.type, "reasoning");
  assert.equal(item?.type === "reasoning" && item.summary[0]?.text, "check the policy");
  assert.equal(item?.type === "reasoning" && item.content?.[0]?.text, "raw thought");
});

test("only the final answer is carried into the next request", () => {
  let turn = emptyTurnState("turn-1");
  turn = reduceResponseStreamEvent(turn, {
    type: "response.completed",
    response: {
      ...envelope("response-1"),
      status: "completed",
      output: [
        message("commentary-1", "Let me check. ", "commentary"),
        message("answer-1", "Leave is 20 days.", "final_answer"),
      ],
    },
  });

  assert.equal(finalTurnText(turn), "Leave is 20 days.");
});

test("a stream error fails the Turn", () => {
  const turn = reduceResponseStreamEvent(emptyTurnState("turn-1"), {
    type: "error",
    error: { type: "error", code: "502", message: "upstream down" },
  });

  assert.equal(turn.status, "failed");
  assert.equal(turn.error, "upstream down");
});

function envelope(id: string) {
  return { id, status: "in_progress" as const, output: [] };
}

function message(id: string, text: string, phase: "commentary" | "final_answer"): OutputItem {
  return {
    type: "message",
    id,
    role: "assistant",
    status: "completed",
    phase,
    content: [{ type: "output_text", text, annotations: [] }],
  };
}

function textOf(turn: TurnState, responseId: string, itemId: string): string {
  const item = turn.responses[responseId]?.items[itemId];
  if (item?.type !== "message") return "";
  const part = item.content[0];
  return part && part.type === "output_text" ? part.text : "";
}

function assistantPlaceholder(id: string): ChatMessage {
  return { id, role: "assistant", parts: [], turn: emptyTurnState(id) };
}
