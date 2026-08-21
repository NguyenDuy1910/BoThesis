"use client";

import type {
  CachedChatMessage,
  ChatMessage,
  ChatMessagePart,
  ChatConversation,
} from "./types";
import { finalTurnText } from "./message-stream.ts";

const CONVERSATIONS_KEY_BASE = "bothesis-conversations";
const MESSAGE_PREFIX_BASE = "bothesis-messages:";
const ANONYMOUS_USER_NAMESPACE = "anonymous";
const DEFAULT_CONVERSATION_TITLE = "New conversation";
let memoryConversations: ChatConversation[] = [];
const memoryMessages = new Map<string, CachedChatMessage[]>();
let activeUserNamespace = ANONYMOUS_USER_NAMESPACE;

function normalizeUserNamespace(identity: string | null | undefined) {
  const value = String(identity ?? "").trim().toLowerCase();
  return value || ANONYMOUS_USER_NAMESPACE;
}

export function setConversationUser(identity: string | null | undefined) {
  const next = normalizeUserNamespace(identity);
  if (next === activeUserNamespace) return;
  activeUserNamespace = next;
  memoryConversations = [];
  memoryMessages.clear();
}

function conversationsKey() {
  return `${CONVERSATIONS_KEY_BASE}:${activeUserNamespace}`;
}

function messageKey(sessionId: string) {
  return `${MESSAGE_PREFIX_BASE}${activeUserNamespace}:${sessionId}`;
}

export interface ConversationAdapter {
  createConversation(
    title?: string,
    id?: string,
    sessionId?: string,
  ): Promise<ChatConversation>;
  listConversations(): Promise<ChatConversation[]>;
  getConversationMessages(id: string): Promise<CachedChatMessage[]>;
  saveConversationMessages(id: string, messages: CachedChatMessage[]): Promise<void>;
  updateConversation(
    id: string,
    patch: Partial<
      Pick<ChatConversation, "title" | "titleSource" | "updatedAt">
    >
  ): Promise<ChatConversation | null>;
  deleteConversation(id: string): Promise<void>;
}

function readConversations(): ChatConversation[] {
  try {
    const raw = window.localStorage.getItem(conversationsKey());
    return normalizeConversations(
      raw ? (JSON.parse(raw) as ChatConversation[]) : memoryConversations
    );
  } catch {
    return normalizeConversations(memoryConversations);
  }
}

function writeConversations(conversations: ChatConversation[]) {
  memoryConversations = conversations;
  try {
    window.localStorage.setItem(conversationsKey(), JSON.stringify(conversations));
  } catch {
    // Keep local-only conversations usable when browser storage is unavailable.
  }
}

function readStoredMessages(id: string): CachedChatMessage[] {
  const sessionId = resolveSessionId(id);
  try {
    const raw = window.localStorage.getItem(messageKey(sessionId));
    return raw
      ? normalizeCachedMessages(JSON.parse(raw) as CachedChatMessage[])
      : normalizeCachedMessages(memoryMessages.get(sessionId) ?? []);
  } catch {
    return normalizeCachedMessages(memoryMessages.get(sessionId) ?? []);
  }
}

function createLocalId(prefix: string) {
  const randomUUID = globalThis.crypto?.randomUUID?.();
  if (randomUUID) return randomUUID;

  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

function normalizeConversations(conversations: ChatConversation[]) {
  return conversations.map((conversation) => ({
    ...conversation,
    sessionId: conversation.sessionId || conversation.id,
  }));
}

function resolveSessionId(id: string) {
  return (
    readConversations().find(
      (conversation) => conversation.id === id || conversation.sessionId === id
    )?.sessionId ?? id
  );
}

function normalizeCachedMessage(message: CachedChatMessage): CachedChatMessage {
  return {
    ...message,
    parts: message.parts.flatMap((part) => {
      const normalized = normalizeStoredPart(part);
      return normalized ? [normalized] : [];
    }),
  };
}

function normalizeStoredPart(part: ChatMessagePart): ChatMessagePart | undefined {
  if (part.type === "text" && part.state === "streaming") {
    return { ...part, state: "done" };
  }
  return part.type === "text" || part.type === "data-document" ? part : undefined;
}

function normalizeCachedMessages(messages: CachedChatMessage[]) {
  return messages.map(normalizeCachedMessage);
}

export function getMessageText(message: ChatMessage): string {
  if (message.role === "assistant") {
    const semanticText = finalTurnText(message.turn);
    if (semanticText) return semanticText;
  }
  return message.parts
    .filter((part): part is Extract<ChatMessagePart, { type: "text" }> => (
      part.type === "text"
    ))
    .map((part) => part.text)
    .join("");
}

export function titleFromMessage(message: string) {
  const cleaned = message.replace(/\s+/g, " ").trim();
  if (!cleaned) return DEFAULT_CONVERSATION_TITLE;
  return cleaned.length > 54 ? `${cleaned.slice(0, 51)}...` : cleaned;
}

export function cachedToUIMessage(message: CachedChatMessage): ChatMessage {
  // An assistant reply's content lives entirely in ``turn`` — its own ``parts``
  // is always empty (see useBothesisChat.ts). Gating this branch on parts alone
  // dropped ``turn`` for every restored assistant message and rendered it as an
  // empty bubble, since AssistantTurn reads only ``turn``.
  if (message.parts.length || message.turn) {
    return {
      id: message.id,
      role: message.role,
      parts: message.parts.flatMap((part) => {
        const normalized = normalizeStoredPart(part);
        return normalized ? [normalized] : [];
      }),
      turn: message.turn,
    };
  }

  return {
    id: message.id,
    role: message.role,
    parts: [{ type: "text", text: message.content, state: "done" }],
  };
}

export function uiToCachedMessage(message: ChatMessage): CachedChatMessage {
  return {
    id: message.id,
    role: message.role === "user" ? "user" : "assistant",
    content: getMessageText(message),
    parts: message.parts.flatMap((part) => {
      const normalized = normalizeStoredPart(part);
      return normalized ? [normalized] : [];
    }),
    turn: message.turn,
    createdAt: Date.now(),
  };
}

export const conversationAdapter: ConversationAdapter = {
  async createConversation(
    title = DEFAULT_CONVERSATION_TITLE,
    id = createLocalId("conversation"),
    sessionId = id,
  ) {
    const existing = readConversations().find((conversation) => conversation.id === id);
    if (existing && existing.deletedAt === undefined) return existing;

    const now = Date.now();
    if (existing) {
      const restored: ChatConversation = {
        ...existing,
        title,
        sessionId,
        updatedAt: now,
        deletedAt: undefined,
      };
      writeConversations(
        readConversations().map((conversation) => (
          conversation.id === id ? restored : conversation
        )),
      );
      return restored;
    }
    const conversation: ChatConversation = {
      id,
      sessionId,
      title,
      titleSource: "generated",
      createdAt: now,
      updatedAt: now,
    };
    // Persist alongside existing conversations — creating a new chat must never
    // remove or overwrite a previous one. Empty drafts are not persisted until
    // the first message is sent, so there is nothing to prune here.
    writeConversations([conversation, ...readConversations()]);
    return conversation;
  },

  async listConversations() {
    return readConversations()
      .filter((conversation) => conversation.deletedAt === undefined)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  },

  async getConversationMessages(id) {
    return readStoredMessages(id);
  },

  async saveConversationMessages(id, messages) {
    const nextMessages = normalizeCachedMessages(messages).slice(-100);
    const sessionId = resolveSessionId(id);
    memoryMessages.set(sessionId, nextMessages);
    try {
      window.localStorage.setItem(
        messageKey(sessionId),
        JSON.stringify(nextMessages)
      );
    } catch {
      // Keep the in-memory fallback alive for restricted browser contexts.
    }
  },

  async updateConversation(id, patch) {
    let updated: ChatConversation | null = null;
    const next = readConversations().map((conversation) => {
      if (conversation.id !== id || conversation.deletedAt !== undefined) {
        return conversation;
      }
      updated = {
        ...conversation,
        ...patch,
        updatedAt: patch.updatedAt ?? Date.now(),
      };
      return updated;
    });
    writeConversations(next);
    return updated;
  },

  async deleteConversation(id) {
    const deletedAt = Date.now();
    writeConversations(readConversations().map((conversation) => (
      conversation.id === id || conversation.sessionId === id
        ? { ...conversation, deletedAt }
        : conversation
    )));
  },
};
