import assert from "node:assert/strict";
import test from "node:test";

import {
  historyFromMessages,
  regenerationContext,
} from "../src/modules/chat/conversation-history.ts";
import type { ChatMessage } from "../src/modules/chat/types.ts";

function message(id: string, role: "user" | "assistant", text: string): ChatMessage {
  return {
    id,
    role,
    parts: [{ type: "text", text, state: "done" }],
  };
}

test("history keeps complete recent turns and excludes activity text", () => {
  const messages: ChatMessage[] = [
    message("old-user", "user", "O".repeat(20_000)),
    message("old-assistant", "assistant", "A".repeat(5_000)),
    message("recent-user", "user", "What are the loan fees?"),
    {
      id: "recent-assistant",
      role: "assistant",
      parts: [
        {
          type: "text",
          id: "commentary",
          text: "Searching internally",
          state: "done",
          phase: "commentary",
        },
        { type: "text", text: "The documented fee is 1%.", state: "done" },
      ],
    },
  ];

  const history = historyFromMessages(messages);

  assert.deepEqual(history.slice(-2), [
    { role: "user", content: "What are the loan fees?" },
    { role: "assistant", content: "The documented fee is 1%." },
  ]);
  assert.equal(history.some((entry) => entry.content.includes("Searching internally")), false);
  assert.equal(history[0]?.role, "user");
});

test("regeneration excludes the replaced answer and current request from history", () => {
  const messages = [
    message("user-1", "user", "Tell me about product Easy"),
    message("assistant-1", "assistant", "Easy is an internal loan product."),
    message("user-2", "user", "What are its fees?"),
    message("assistant-2", "assistant", "Old answer"),
  ];

  const context = regenerationContext(messages, "assistant-2");

  assert.equal(context?.userText, "What are its fees?");
  assert.deepEqual(context?.historyMessages, messages.slice(0, 2));
  assert.deepEqual(context?.displayMessages, messages.slice(0, 3));
});

test("oversized messages preserve both the subject and the latest details", () => {
  const longAnswer = `Subject: Easy loan\n${"A".repeat(9_000)}\nFinal fee: 1%`;

  const history = historyFromMessages([
    message("user", "user", "Tell me about Easy loan"),
    message("assistant", "assistant", longAnswer),
  ]);

  assert.equal(history[1]?.content.length, 8_000);
  assert.match(history[1]?.content ?? "", /^Subject: Easy loan/);
  assert.match(history[1]?.content ?? "", /Final fee: 1%$/);
});
