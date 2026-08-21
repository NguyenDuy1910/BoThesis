"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getBothesisChatConfiguration } from "@/lib/api/config";
import { streamAgentResponse } from "../api";
import { historyFromMessages, regenerationContext } from "../conversation-history";
import { applyAgentStreamEvent, updateRun } from "../message-stream";
import type {
  AgentStreamEvent,
  ChatMessage,
  ConversationDocument,
} from "../types";

type ChatStatus = "ready" | "submitted" | "streaming";

function messageId(prefix: string) {
  return globalThis.crypto?.randomUUID?.() ?? `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useBothesisChat({
  conversationId,
  initialMessages,
  onFinish,
}: {
  conversationId: string;
  initialMessages: ChatMessage[];
  onFinish?: (messages: ChatMessage[]) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [status, setStatus] = useState<ChatStatus>("ready");
  const [error, setError] = useState<Error | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const messagesRef = useRef(messages);
  const onFinishRef = useRef(onFinish);
  const activeAssistantIdRef = useRef<string | null>(null);
  messagesRef.current = messages;
  onFinishRef.current = onFinish;
  const isConfigured = Boolean(getBothesisChatConfiguration());

  // Reset on a real conversation switch only. ``initialMessages`` gets a fresh
  // array identity from every ChatShell refresh — including the ones behind
  // rename, delete, and the save that follows each completed turn — and keying
  // the reset on it aborted the in-flight stream and dropped ``runtime`` from
  // the messages it replaced. The rehydrated copy is what we just persisted, so
  // there is nothing to adopt for a conversation already on screen.
  const loadedConversationRef = useRef(conversationId);
  useEffect(() => {
    if (loadedConversationRef.current === conversationId) return;
    loadedConversationRef.current = conversationId;
    controllerRef.current?.abort();
    controllerRef.current = null;
    messagesRef.current = initialMessages;
    setMessages(initialMessages);
    setStatus("ready");
    setError(null);
    activeAssistantIdRef.current = null;
  }, [conversationId, initialMessages]);

  // Leaving the conversation must not leave the request running.
  useEffect(() => () => controllerRef.current?.abort(), []);

  const updateAssistant = useCallback((assistantId: string, event: AgentStreamEvent) => {
    // The stream can deliver its first event before React commits the render
    // that inserted the assistant placeholder. Reduce against the synchronous
    // ref first so no SSE event (especially ``turn.completed``) is dropped or
    // later overwritten by a stale queued state update.
    const next = applyAgentStreamEvent(messagesRef.current, assistantId, event);
    messagesRef.current = next;
    setMessages(next);
  }, []);

  const run = useCallback(async (
    text: string,
    includeUserMessage: boolean,
    options: {
      historyMessages?: ChatMessage[];
      displayMessages?: ChatMessage[];
      documents?: ConversationDocument[];
    } = {},
  ) => {
    if (controllerRef.current) return;
    const history = historyFromMessages(options.historyMessages ?? messagesRef.current);
    const controller = new AbortController();
    controllerRef.current = controller;
    setError(null);
    setStatus("submitted");

    const assistantId = messageId("assistant");
    const assistant: ChatMessage = {
      id: assistantId,
      role: "assistant",
      parts: [{
        type: "data-run",
        id: "run",
        data: { status: "running", startedAt: Date.now() },
      }],
    };
    activeAssistantIdRef.current = assistantId;
    const baseMessages = options.displayMessages ?? messagesRef.current;
    const nextMessages = includeUserMessage
      ? [...baseMessages, {
          id: messageId("user"),
          role: "user" as const,
          parts: [
            { type: "text" as const, text, state: "done" as const },
            ...(options.documents ?? []).map((document) => ({
              type: "data-document" as const,
              id: document.id,
              data: document,
            })),
          ],
        }, assistant]
      : [...baseMessages, assistant];
    messagesRef.current = nextMessages;
    setMessages(nextMessages);

    try {
      await streamAgentResponse(text, {
        conversationId,
        history,
        documentIds: options.documents?.map((document) => document.id),
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "item.delta") {
            setStatus("streaming");
          }
          updateAssistant(assistantId, event);
          if (event.type === "error") setError(new Error(event.message));
        },
      });
      if (!controller.signal.aborted) {
        const completed = messagesRef.current.map((message) => ({
          ...message,
          parts: message.parts.map((part) => part.type === "text" ? { ...part, state: "done" as const } : part),
        }));
        messagesRef.current = completed;
        setMessages(completed);
        onFinishRef.current?.(completed);
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        const nextError = cause instanceof Error ? cause : new Error("Chat request failed.");
        setError(nextError);
        updateAssistant(assistantId, { type: "error", message: nextError.message });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        activeAssistantIdRef.current = null;
        setStatus("ready");
      }
    }
  }, [conversationId, updateAssistant]);

  const sendMessage = useCallback(async ({
    text,
    documents = [],
  }: {
    text: string;
    documents?: ConversationDocument[];
  }) => run(text, true, { documents }), [run]);
  const stop = useCallback(() => {
    const activeAssistantId = activeAssistantIdRef.current;
    controllerRef.current?.abort();
    controllerRef.current = null;
    activeAssistantIdRef.current = null;
    if (activeAssistantId) {
      setMessages((current) => {
        const next = current.map((message) => message.id === activeAssistantId
          ? { ...message, parts: updateRun(message.parts, { status: "cancelled" }) }
          : message);
        messagesRef.current = next;
        return next;
      });
    }
    setStatus("ready");
  }, []);
  const clearError = useCallback(() => setError(null), []);
  const regenerate = useCallback(async ({ messageId: targetId }: { messageId?: string } = {}) => {
    const context = regenerationContext(messagesRef.current, targetId);
    if (!context) return;
    await run(context.userText, false, {
      historyMessages: context.historyMessages,
      displayMessages: context.displayMessages,
      documents: context.documents,
    });
  }, [run]);

  return { messages, sendMessage, regenerate, status, stop, error, clearError, isConfigured };
}
