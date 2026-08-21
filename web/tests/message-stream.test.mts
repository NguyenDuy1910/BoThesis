import assert from "node:assert/strict";
import test from "node:test";

import {
  applyResponseStreamEvent,
  emptyTurnState,
} from "../src/modules/chat/message-stream.ts";
import type { ChatMessage, OutputItem } from "../src/modules/chat/types.ts";

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
    type: "response.created", response_id: response.id, response,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.added", response_id: response.id, output_index: 0, item: message,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.content_part.added", response_id: response.id, item_id: "message-1",
    output_index: 0, content_index: 0, part: { type: "output_text", text: "", annotations: [] },
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.delta", response_id: response.id, item_id: "message-1",
    output_index: 0, content_index: 0, delta: "Grounded ",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.annotation.added", response_id: response.id, item_id: "message-1",
    output_index: 0, content_index: 0,
    annotation: {
      type: "citation",
      start_index: 9,
      end_index: 9,
      citation: { id: "source-1", title: "Access Policy", uri: "https://kb/source-1" },
    },
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_text.delta", response_id: response.id, item_id: "message-1",
    output_index: 0, content_index: 0, delta: "answer.",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.done", response_id: response.id, output_index: 0,
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
    type: "response.created", response_id: response.id, response,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.output_item.added", response_id: response.id, output_index: 0, item: functionCall,
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.function_call_arguments.delta", response_id: response.id, item_id: "call-item-1",
    output_index: 0, delta: "{\"query\":\"policy",
  });
  messages = applyResponseStreamEvent(messages, assistantId, {
    type: "response.function_call_arguments.done", response_id: response.id, item_id: "call-item-1",
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

function assistantPlaceholder(id: string): ChatMessage {
  return { id, role: "assistant", parts: [], turn: emptyTurnState(id) };
}
