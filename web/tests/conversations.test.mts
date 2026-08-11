import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationAdapter,
  setConversationUser,
} from "../src/modules/chat/conversations.ts";

class MemoryStorage {
  private values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }

  removeItem(key: string) {
    this.values.delete(key);
  }
}

test("conversation adapter persists custom rename metadata and confirmed deletion", async () => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new MemoryStorage() },
  });
  setConversationUser("sidebar-actions-test");

  await conversationAdapter.createConversation("Generated title", "chat-1", "session-1");
  const renamed = await conversationAdapter.updateConversation("chat-1", {
    title: "Quarterly planning",
    titleSource: "custom",
  });

  assert.equal(renamed?.title, "Quarterly planning");
  assert.equal(renamed?.titleSource, "custom");
  assert.equal((await conversationAdapter.listConversations()).length, 1);

  await conversationAdapter.deleteConversation("chat-1");
  assert.deepEqual(await conversationAdapter.listConversations(), []);
});
