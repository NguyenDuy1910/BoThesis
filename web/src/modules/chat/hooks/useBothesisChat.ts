"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getBothesisChatConfiguration } from "@/lib/api/config";
import { streamAgentResponse } from "../api";
import type {
  AgentEvidence,
  AgentHistoryMessage,
  AgentStreamEvent,
  ChatMessage,
  ChatMessagePart,
} from "../types";

type ChatStatus = "ready" | "submitted" | "streaming";
const MAX_HISTORY_MESSAGES = 8;
const MAX_HISTORY_CHARACTERS = 8_000;

function messageId(prefix: string) {
  return globalThis.crypto?.randomUUID?.() ?? `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function messageText(message: ChatMessage) {
  return message.parts
    .filter((part): part is Extract<ChatMessagePart, { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function historyFromMessages(messages: ChatMessage[]): AgentHistoryMessage[] {
  let remainingCharacters = MAX_HISTORY_CHARACTERS;
  const history: AgentHistoryMessage[] = [];
  for (const message of [...messages].reverse()) {
    const content = messageText(message).trim();
    if (!content || remainingCharacters <= 0) continue;
    history.push({
      role: message.role,
      content: content.slice(-remainingCharacters),
    });
    remainingCharacters -= content.length;
    if (history.length === MAX_HISTORY_MESSAGES) break;
  }
  return history.reverse();
}

function appendEvent(parts: ChatMessagePart[], event: AgentStreamEvent): ChatMessagePart[] {
  if (event.type === "run_started") {
    return updateRun(parts, {
      status: "running",
      requestId: event.request_id ?? undefined,
      conversationId: event.conversation_id ?? undefined,
    });
  }
  if (event.type === "message_delta") {
    const last = parts.at(-1);
    if (last?.type === "text") {
      return [...parts.slice(0, -1), { ...last, text: last.text + event.text, state: "streaming" }];
    }
    return [...parts, { type: "text", text: event.text, state: "streaming" }];
  }
  if (event.type === "tool_started") {
    const isRetrieval = event.name === "knowledge_search";
    return [...parts, {
      type: "data-status",
      id: `tool-${event.call_id}-started`,
      data: {
        phase: isRetrieval ? "retrieval" : "tool",
        state: "active",
        label: isRetrieval ? "Searching knowledge base" : `Using ${event.name}`,
        toolName: event.name,
        toolCallId: event.call_id,
        query: displayableQuery(event.arguments),
      },
    }];
  }
  if (event.type === "tool_completed") {
    const isRetrieval = event.name === "knowledge_search";
    const detail = event.error
      ? event.error
      : event.result_count === undefined
        ? undefined
        : `Found ${event.result_count} source${event.result_count === 1 ? "" : "s"}.`;
    return [...parts, {
      type: "data-status",
      id: `tool-${event.call_id}-complete`,
      data: {
        phase: isRetrieval ? "retrieval" : "tool",
        state: event.error ? "error" : "completed",
        label: event.error ? `${event.name} could not complete` : `${event.name} completed`,
        detail,
        toolName: event.name,
        toolCallId: event.call_id,
        durationMs: event.duration_ms ?? undefined,
        resultCount: event.result_count ?? undefined,
      },
    }];
  }
  if (event.type === "citation_available") {
    return [...parts, sourcePart(event.evidence)];
  }
  if (event.type === "citation") {
    return appendCitation(parts, event.evidence_id, event.title);
  }
  if (event.type === "run_failed") {
    return updateRun([...parts, {
      type: "data-stream-error",
      id: "stream-error",
      data: { message: event.error, retryable: true },
    }], { status: "failed" });
  }
  if (event.type === "run_completed") {
    return updateRun(
      parts.map((part) => part.type === "text" ? { ...part, state: "done" } : part),
      {
        status: "completed",
        durationMs: event.duration_ms ?? undefined,
        modelDurationMs: event.model_duration_ms ?? undefined,
        toolDurationMs: event.tool_duration_ms ?? undefined,
        toolCallCount: event.tool_call_count ?? undefined,
      },
    );
  }
  return parts;
}

type RunPart = Extract<ChatMessagePart, { type: "data-run" }>;

function updateRun(
  parts: ChatMessagePart[],
  patch: Partial<RunPart["data"]>,
): ChatMessagePart[] {
  const index = parts.findIndex((part) => part.type === "data-run");
  if (index === -1) {
    const run: RunPart = {
      type: "data-run",
      id: "run",
      data: { status: "running", startedAt: Date.now(), ...patch },
    };
    return [...parts, run];
  }
  const currentRun = parts[index] as RunPart;
  const run: RunPart = { ...currentRun, data: { ...currentRun.data, ...patch } };
  return [
    ...parts.slice(0, index),
    run,
    ...parts.slice(index + 1),
  ];
}

function displayableQuery(arguments_: Record<string, unknown>) {
  const query = arguments_.query;
  if (typeof query !== "string") return undefined;
  const normalizedQuery = query.trim();
  return normalizedQuery ? normalizedQuery.slice(0, 512) : undefined;
}

function appendCitation(parts: ChatMessagePart[], evidenceId: string, title: string) {
  const nextParts = parts.map((part) => (
    part.type === "data-source" && part.data.id === evidenceId
      ? { ...part, data: { ...part.data, status: "Used" as const } }
      : part
  ));
  const textIndex = [...nextParts].map((part) => part.type).lastIndexOf("text");
  if (textIndex === -1) return nextParts;

  const text = nextParts[textIndex] as Extract<ChatMessagePart, { type: "text" }>;
  const safeTitle = title.replace(/[\\[\\]]/g, "\\$&").trim() || "Source";
  const citation = ` [${safeTitle}](#source-${encodeURIComponent(evidenceId)})`;
  return [
    ...nextParts.slice(0, textIndex),
    { ...text, text: `${text.text}${citation}` },
    ...nextParts.slice(textIndex + 1),
  ];
}

function sourcePart(evidence: AgentEvidence): Extract<ChatMessagePart, { type: "data-source" }> {
  return {
    type: "data-source",
    id: evidence.id,
    data: {
      id: evidence.id,
      title: evidence.title,
      url: evidence.uri ?? undefined,
      description: evidence.section ?? evidence.page ?? undefined,
      status: "Found",
      source: evidence.source ?? undefined,
      relevanceScore: evidence.relevance_score ?? undefined,
    },
  };
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

  useEffect(() => {
    controllerRef.current?.abort();
    setMessages(initialMessages);
    setStatus("ready");
    setError(null);
    activeAssistantIdRef.current = null;
  }, [conversationId, initialMessages]);

  const updateAssistant = useCallback((assistantId: string, event: AgentStreamEvent) => {
    setMessages((current) => {
      const next = current.map((message) => message.id === assistantId
        ? { ...message, parts: appendEvent(message.parts, event) }
        : message);
      messagesRef.current = next;
      return next;
    });
  }, []);

  const run = useCallback(async (text: string, includeUserMessage: boolean) => {
    if (controllerRef.current) return;
    const history = historyFromMessages(messagesRef.current);
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
    setMessages((current) => {
      const next = includeUserMessage
        ? [...current, { id: messageId("user"), role: "user" as const, parts: [{ type: "text" as const, text, state: "done" as const }] }, assistant]
        : [...current, assistant];
      messagesRef.current = next;
      return next;
    });

    try {
      await streamAgentResponse(text, {
        conversationId,
        history,
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "message_delta") setStatus("streaming");
          updateAssistant(assistantId, event);
          if (event.type === "run_failed") setError(new Error(event.error));
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
        updateAssistant(assistantId, { type: "run_failed", error: nextError.message });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        activeAssistantIdRef.current = null;
        setStatus("ready");
      }
    }
  }, [conversationId, updateAssistant]);

  const sendMessage = useCallback(async ({ text }: { text: string }) => run(text, true), [run]);
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
    const current = messagesRef.current;
    const targetIndex = targetId ? current.findIndex((message) => message.id === targetId) : current.length;
    const user = current.slice(0, targetIndex).reverse().find((message) => message.role === "user");
    if (!user) return;
    const userText = messageText(user);
    if (!userText) return;
    setMessages(current.slice(0, current.indexOf(user) + 1));
    await run(userText, false);
  }, [run]);

  return { messages, sendMessage, regenerate, status, stop, error, clearError, isConfigured };
}
