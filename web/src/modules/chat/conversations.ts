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
const SELECTED_CONVERSATION_KEY_BASE = "bothesis-selected-conversation";
const ANONYMOUS_USER_NAMESPACE = "anonymous";
const DEFAULT_CONVERSATION_TITLE = "New conversation";
let memoryConversations: ChatConversation[] = [];
const memoryMessages = new Map<string, CachedChatMessage[]>();
let activeUserNamespace = ANONYMOUS_USER_NAMESPACE;
let activeSessionKind: "user" | "guest" = "user";

function normalizeUserNamespace(identity: string | null | undefined) {
  const value = String(identity ?? "").trim().toLowerCase();
  return value || ANONYMOUS_USER_NAMESPACE;
}

/** Keep browser-local drafts isolated by both signed-in user and active tenant. */
export function setConversationUser(
  identity: string | null | undefined,
  tenantId?: string | null,
  sessionKind: "user" | "guest" = "user",
) {
  const user = normalizeUserNamespace(identity);
  const tenant = normalizeUserNamespace(tenantId);
  const next = `${user}:${tenant}`;
  if (next === activeUserNamespace && sessionKind === activeSessionKind) return;
  activeUserNamespace = next;
  activeSessionKind = sessionKind;
  memoryConversations = [];
  memoryMessages.clear();
}

function conversationStorage(): Storage {
  return activeSessionKind === "guest" ? window.sessionStorage : window.localStorage;
}

/** Move browser-held conversation presentation state after a guest is claimed. */
export function migrateConversationUser(
  fromUserId: string,
  fromTenantId: string,
  toUserId: string,
  toTenantId: string,
): void {
  if (typeof window === "undefined") return;
  const from = `${normalizeUserNamespace(fromUserId)}:${normalizeUserNamespace(fromTenantId)}`;
  const to = `${normalizeUserNamespace(toUserId)}:${normalizeUserNamespace(toTenantId)}`;
  if (from === to) return;
  try {
    const conversationSource = `${CONVERSATIONS_KEY_BASE}:${from}`;
    const conversationTarget = `${CONVERSATIONS_KEY_BASE}:${to}`;
    const conversations = window.sessionStorage.getItem(conversationSource);
    if (conversations) {
      const guestConversations = normalizeConversations(
        JSON.parse(conversations) as ChatConversation[],
      );
      const existing = window.localStorage.getItem(conversationTarget);
      const authenticatedConversations = normalizeConversations(
        existing ? JSON.parse(existing) as ChatConversation[] : [],
      );
      const merged = [...guestConversations, ...authenticatedConversations].filter(
        (conversation, index, all) => all.findIndex(
          (candidate) => candidate.id === conversation.id,
        ) === index,
      );
      window.localStorage.setItem(conversationTarget, JSON.stringify(merged));
      for (const conversation of guestConversations) {
        const source = `${MESSAGE_PREFIX_BASE}${from}:${conversation.sessionId}`;
        const target = `${MESSAGE_PREFIX_BASE}${to}:${conversation.sessionId}`;
        const messages = window.sessionStorage.getItem(source);
        if (messages) window.localStorage.setItem(target, messages);
      }
    }
    const selected = window.sessionStorage.getItem(
      `${SELECTED_CONVERSATION_KEY_BASE}:${from}`,
    );
    if (selected !== null) {
      window.sessionStorage.setItem(`${SELECTED_CONVERSATION_KEY_BASE}:${to}`, selected);
    }
  } catch {
    // Server ownership still transfers; restricted storage only loses local UI metadata.
  }
  setConversationUser(toUserId, toTenantId, "user");
}

function conversationsKey() {
  return `${CONVERSATIONS_KEY_BASE}:${activeUserNamespace}`;
}

function messageKey(sessionId: string) {
  return `${MESSAGE_PREFIX_BASE}${activeUserNamespace}:${sessionId}`;
}

function selectedConversationKey() {
  return `${SELECTED_CONVERSATION_KEY_BASE}:${activeUserNamespace}`;
}

/** A tab remembers whether it was showing a conversation or an empty draft. */
export function readSelectedConversation(): string | null | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const stored = window.sessionStorage.getItem(selectedConversationKey());
    return stored === null ? undefined : stored || null;
  } catch {
    return undefined;
  }
}

export function rememberSelectedConversation(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(selectedConversationKey(), id ?? "");
  } catch {
    // Restricted storage should not prevent navigation within Chat.
  }
}

/** An explicit empty draft must not silently reopen the newest conversation. */
export function resolveSelectedConversation(
  conversations: ChatConversation[],
  requestedId: string | null | undefined,
): string | null {
  if (requestedId === null) return null;
  return requestedId && conversations.some((item) => item.id === requestedId)
    ? requestedId
    : conversations[0]?.id ?? null;
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
    const raw = conversationStorage().getItem(conversationsKey());
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
    conversationStorage().setItem(conversationsKey(), JSON.stringify(conversations));
  } catch {
    // Keep local-only conversations usable when browser storage is unavailable.
  }
}

function readStoredMessages(id: string): CachedChatMessage[] {
  const sessionId = resolveSessionId(id);
  try {
    const raw = conversationStorage().getItem(messageKey(sessionId));
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
  return part.type === "text" || part.type === "data-document" || part.type === "data-collection"
    ? part
    : undefined;
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
  return cleaned.length > 54 ? `${cleaned.slice(0, 51)}…` : cleaned;
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
  const turn = message.turn && withoutTransientTurnState(message.turn);
  return {
    id: message.id,
    role: message.role === "user" ? "user" : "assistant",
    content: getMessageText(message),
    parts: message.parts.flatMap((part) => {
      const normalized = normalizeStoredPart(part);
      return normalized ? [normalized] : [];
    }),
    turn,
    createdAt: Date.now(),
  };
}

function withoutTransientTurnState(turn: NonNullable<ChatMessage["turn"]>) {
  const { modelPending: _modelPending, runtimeActivities: _runtimeActivities, ...stored } = turn;
  return stored;
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
      conversationStorage().setItem(
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
