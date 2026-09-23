import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationAdapter,
  migrateConversationUser,
  readSelectedConversation,
  rememberSelectedConversation,
  resolveSelectedConversation,
  setConversationUser,
  uiToCachedMessage,
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
  await conversationAdapter.saveConversationMessages("chat-1", [
    {
      id: "message-1",
      role: "user",
      content: "Retain this message",
      parts: [{ type: "text", text: "Retain this message", state: "done" }],
      createdAt: Date.now(),
    },
  ]);

  await conversationAdapter.deleteConversation("chat-1");
  assert.deepEqual(await conversationAdapter.listConversations(), []);
  assert.equal(
    (await conversationAdapter.getConversationMessages("chat-1"))[0]?.content,
    "Retain this message",
  );
});

test("does not persist pending or runtime activity as conversation history", () => {
  const cached = uiToCachedMessage({
    id: "assistant-1",
    role: "assistant",
    parts: [],
    turn: {
      id: "assistant-1",
      status: "streaming",
      responses: {},
      responseOrder: [],
      modelPending: true,
      runtimeActivities: [{
        callId: "call-1",
        toolName: "knowledge_search",
        state: "active",
        startedAt: Date.now(),
      }],
    },
  });

  assert.equal(cached.turn?.modelPending, undefined);
  assert.equal(cached.turn?.runtimeActivities, undefined);
});

test("retains collection context on a persisted user turn", async () => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new MemoryStorage() },
  });
  setConversationUser("collection-context-test");

  await conversationAdapter.createConversation("Policy question", "chat-collections");
  await conversationAdapter.saveConversationMessages("chat-collections", [{
    id: "message-collection",
    role: "user",
    content: "What changed in the policy?",
    parts: [
      { type: "text", text: "What changed in the policy?", state: "done" },
      {
        type: "data-collection",
        id: "collection-policy",
        data: { id: "collection-policy", title: "Policy workspace" },
      },
    ],
    createdAt: Date.now(),
  }]);

  const restored = await conversationAdapter.getConversationMessages("chat-collections");
  assert.equal(restored[0]?.parts[1]?.type, "data-collection");
});

test("restores selection and conversation data only within the active workspace", async () => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new MemoryStorage(), sessionStorage: new MemoryStorage() },
  });
  setConversationUser("chat-restore-test", "workspace-a");
  assert.equal(readSelectedConversation(), undefined);

  await conversationAdapter.createConversation("Workspace A chat", "conversation-1");
  rememberSelectedConversation("conversation-1");
  assert.equal(readSelectedConversation(), "conversation-1");

  setConversationUser("chat-restore-test", "workspace-b");
  assert.equal(readSelectedConversation(), undefined);
  assert.deepEqual(await conversationAdapter.listConversations(), []);

  setConversationUser("chat-restore-test", "workspace-a");
  assert.deepEqual(
    (await conversationAdapter.listConversations()).map(({ id }) => id),
    ["conversation-1"],
  );
  assert.equal(readSelectedConversation(), "conversation-1");
  rememberSelectedConversation(null);
  assert.equal(readSelectedConversation(), null);
});

test("an empty draft stays empty while a missing saved chat falls back to recents", () => {
  const conversations = [{ id: "latest" }, { id: "older" }] as Awaited<ReturnType<typeof conversationAdapter.listConversations>>;
  assert.equal(resolveSelectedConversation(conversations, null), null);
  assert.equal(resolveSelectedConversation(conversations, "older"), "older");
  assert.equal(resolveSelectedConversation(conversations, "missing"), "latest");
  assert.equal(resolveSelectedConversation(conversations, undefined), "latest");
});

test("claiming a guest keeps current chat and existing authenticated history", async () => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage: new MemoryStorage(), sessionStorage: new MemoryStorage() },
  });

  setConversationUser("member", "public", "user");
  await conversationAdapter.createConversation("Existing chat", "existing-chat");
  await conversationAdapter.saveConversationMessages("existing-chat", [{
    id: "existing-message",
    role: "user",
    content: "Existing history",
    parts: [{ type: "text", text: "Existing history", state: "done" }],
    createdAt: Date.now(),
  }]);

  setConversationUser("guest", "public", "guest");
  await conversationAdapter.createConversation("Guest chat", "guest-chat");
  await conversationAdapter.saveConversationMessages("guest-chat", [{
    id: "guest-message",
    role: "user",
    content: "Keep this position",
    parts: [{ type: "text", text: "Keep this position", state: "done" }],
    createdAt: Date.now(),
  }]);
  rememberSelectedConversation("guest-chat");

  migrateConversationUser("guest", "public", "member", "public");

  assert.deepEqual(
    (await conversationAdapter.listConversations()).map(({ id }) => id),
    ["guest-chat", "existing-chat"],
  );
  assert.equal(
    (await conversationAdapter.getConversationMessages("guest-chat"))[0]?.content,
    "Keep this position",
  );
  assert.equal(
    (await conversationAdapter.getConversationMessages("existing-chat"))[0]?.content,
    "Existing history",
  );
  assert.equal(readSelectedConversation(), "guest-chat");
});
