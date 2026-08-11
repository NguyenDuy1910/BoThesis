"use client";

import clsx from "clsx";
import {
  BarChart3,
  Check,
  Copy,
  FileSearch,
  ListChecks,
  LoaderCircle,
  Menu,
  PanelRight,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Square,
} from "lucide-react";
import { memo, type FormEvent, type MouseEvent, type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useClipboard } from "@/lib/hooks/useClipboard";
import { getBothesisChatConfiguration } from "@/lib/api/config";
import {
  cachedToUIMessage,
  conversationAdapter,
  getMessageText,
  setConversationUser,
  titleFromMessage,
  uiToCachedMessage,
} from "@/modules/chat/conversations";
import { useBothesisChat } from "@/modules/chat/hooks/useBothesisChat";
import { useSidebarState } from "@/modules/chat/hooks/useSidebarState";
import type { ChatConversation, ChatMessage, ChatMessagePart } from "@/modules/chat/types";
import { AgentActivityPanel, AgentExecutionCard } from "./AgentExecutionCard";
import { AppSidebar, BothesisMark } from "./AppSidebar";
import { IncrementalMarkdown } from "./IncrementalMarkdown";

const suggestions = [
  {
    title: "Executive briefing",
    description: "Summarize priorities, blockers, and source-backed decisions.",
    prompt: "Summarize the latest executive priorities from the knowledge base with sources.",
    icon: FileSearch,
  },
  {
    title: "Risk review",
    description: "Surface exceptions, policy gaps, and operating signals.",
    prompt: "What risks should leadership review this week, and what evidence supports them?",
    icon: BarChart3,
  },
  {
    title: "Decision memo",
    description: "Draft a concise decision memo from the most relevant internal context.",
    prompt: "Draft a concise decision memo from the most relevant internal context.",
    icon: Sparkles,
  },
  {
    title: "Source lookup",
    description: "Find policy details, owners, and referenced documents.",
    prompt: "Find policy details related to internal permissions and cite the source documents.",
    icon: ListChecks,
  },
];

function createDraftConversationId() {
  return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function ChatShell() {
  const sidebar = useSidebarState();
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState(createDraftConversationId);
  const [initialMessages, setInitialMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async (requestedId?: string | null) => {
    const list = await conversationAdapter.listConversations();
    const selectedId = requestedId && list.some((item) => item.id === requestedId)
      ? requestedId
      : list[0]?.id ?? null;
    const messages = selectedId
      ? (await conversationAdapter.getConversationMessages(selectedId)).map(cachedToUIMessage)
      : [];
    setConversations(list);
    setActiveId(selectedId);
    setInitialMessages(messages);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    setConversationUser(getBothesisChatConfiguration()?.userId);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!sidebar.mobileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") sidebar.closeMobile();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [sidebar.closeMobile, sidebar.mobileOpen]);

  const startNewChat = useCallback(() => {
    setDraftId(createDraftConversationId());
    setActiveId(null);
    setInitialMessages([]);
    sidebar.closeMobile();
  }, [sidebar]);

  const selectConversation = useCallback(async (id: string) => {
    sidebar.closeMobile();
    await refresh(id);
  }, [refresh, sidebar]);

  const deleteConversation = useCallback(async (id: string) => {
    await conversationAdapter.deleteConversation(id);
    await refresh(id === activeId ? undefined : activeId);
  }, [activeId, refresh]);

  const renameConversation = useCallback(async (id: string, title: string) => {
    await conversationAdapter.updateConversation(id, {
      title,
      titleSource: "custom",
    });
    await refresh(activeId);
  }, [activeId, refresh]);

  const saveMessages = useCallback(async (conversationId: string, messages: ChatMessage[]) => {
    const firstUserMessage = messages.find((message) => message.role === "user");
    if (!firstUserMessage) return;

    let persistedId = conversationId;
    if (!conversations.some((conversation) => conversation.id === conversationId)) {
      const created = await conversationAdapter.createConversation(
        titleFromMessage(getMessageText(firstUserMessage)),
        conversationId,
      );
      persistedId = created.id;
    }
    await conversationAdapter.saveConversationMessages(
      persistedId,
      messages.map(uiToCachedMessage),
    );
    const existingConversation = conversations.find(
      (conversation) => conversation.id === persistedId,
    );
    if (existingConversation?.titleSource !== "custom") {
      await conversationAdapter.updateConversation(persistedId, {
        title: titleFromMessage(getMessageText(firstUserMessage)),
        titleSource: "generated",
      });
    }
    await refresh(persistedId);
  }, [conversations, refresh]);

  return (
    <div className="app-shell">
      <AppSidebar
        activeId={activeId}
        collapsed={sidebar.collapsed}
        conversations={conversations}
        isLoading={isLoading}
        mobileOpen={sidebar.mobileOpen}
        onCloseMobile={sidebar.closeMobile}
        onDeleteConversation={deleteConversation}
        onNewChat={startNewChat}
        onRenameConversation={renameConversation}
        onSelectConversation={(id) => void selectConversation(id)}
        onToggleCollapse={sidebar.toggleCollapse}
      />
      {sidebar.mobileOpen && (
        <button
          aria-label="Close conversation sidebar"
          className="sidebar-overlay sidebar-overlay--visible"
          onClick={sidebar.closeMobile}
          type="button"
        />
      )}
      <ChatConversation
        key={activeId ?? draftId}
        conversationId={activeId ?? draftId}
        conversationTitle={conversations.find((conversation) => conversation.id === activeId)?.title ?? null}
        initialMessages={initialMessages}
        onMessagesSaved={saveMessages}
        onOpenSidebar={sidebar.openMobile}
      />
    </div>
  );
}

function ChatConversation({
  conversationId,
  conversationTitle,
  initialMessages,
  onMessagesSaved,
  onOpenSidebar,
}: {
  conversationId: string;
  conversationTitle: string | null;
  initialMessages: ChatMessage[];
  onMessagesSaved: (conversationId: string, messages: ChatMessage[]) => Promise<void>;
  onOpenSidebar: () => void;
}) {
  const [input, setInput] = useState("");
  const [sourceFocus, setSourceFocus] = useState<{
    messageId: string;
    sourceId: string;
    nonce: number;
  } | null>(null);
  const [activityOpen, setActivityOpen] = useState(false);
  const [selectedActivityMessageId, setSelectedActivityMessageId] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const messageStackRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const positionedTurnRef = useRef<string | null>(null);
  const didInitialScrollRef = useRef(false);
  const {
    messages,
    sendMessage,
    regenerate,
    status,
    stop,
    error,
    clearError,
    isConfigured,
  } = useBothesisChat({
    conversationId,
    initialMessages,
    onFinish: (completedMessages) => {
      void onMessagesSaved(conversationId, completedMessages);
    },
  });
  const isStreaming = status === "submitted" || status === "streaming";
  const lastMessage = messages.at(-1);
  const precedingMessage = messages.at(-2);
  const latestUserMessageId = precedingMessage?.role === "user"
    ? precedingMessage.id
    : latestMessageId(messages, "user");
  const activeAssistantMessageId = isStreaming && lastMessage?.role === "assistant"
    ? lastMessage.id
    : null;
  const activeTurnId = latestUserMessageId && activeAssistantMessageId
    ? `${latestUserMessageId}:${activeAssistantMessageId}`
    : null;
  const latestAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  const selectedActivityMessage = messages.find(
    (message) => message.id === selectedActivityMessageId && message.role === "assistant",
  ) ?? latestAssistantMessage;
  const selectedActivityIsStreaming = Boolean(
    isStreaming && selectedActivityMessage?.id === activeAssistantMessageId,
  );
  const hasMessageError = messages.some((message) => (
    message.parts.some((part) => part.type === "data-stream-error")
  ));

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [input]);

  useEffect(() => {
    if (activeAssistantMessageId) setSelectedActivityMessageId(activeAssistantMessageId);
  }, [activeAssistantMessageId]);

  useEffect(() => {
    if (selectedActivityMessageId || !latestAssistantMessage) return;
    setSelectedActivityMessageId(latestAssistantMessage.id);
  }, [latestAssistantMessage, selectedActivityMessageId]);

  useLayoutEffect(() => {
    if (!activeTurnId || positionedTurnRef.current === activeTurnId) return;
    const scroller = chatScrollRef.current;
    const stack = messageStackRef.current;
    if (!scroller || !stack) return;

    const userRows = stack.querySelectorAll<HTMLElement>('[data-chat-role="user"]');
    const activeUserRow = userRows[userRows.length - 1];
    if (!activeUserRow) return;

    positionedTurnRef.current = activeTurnId;
    didInitialScrollRef.current = true;
    reserveActiveTurnSpace(scroller, stack);

    const scrollerRect = scroller.getBoundingClientRect();
    const userRect = activeUserRow.getBoundingClientRect();
    const targetTop = scroller.scrollTop + userRect.top - scrollerRect.top - 16;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scroller.scrollTo({
      top: Math.max(0, targetTop),
      behavior: reducedMotion ? "auto" : "smooth",
    });
  }, [activeTurnId]);

  useLayoutEffect(() => {
    if (didInitialScrollRef.current || isStreaming || messages.length === 0) return;
    const scroller = chatScrollRef.current;
    if (!scroller) return;
    didInitialScrollRef.current = true;
    scroller.scrollTop = scroller.scrollHeight;
  }, [isStreaming, messages.length]);

  useEffect(() => {
    const scroller = chatScrollRef.current;
    const stack = messageStackRef.current;
    if (!scroller || !stack || !positionedTurnRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => reserveActiveTurnSpace(scroller, stack));
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [messages.length]);

  const submit = useCallback(async (value: string) => {
    const text = value.trim();
    if (!text || isStreaming || !isConfigured) return;
    clearError();
    setInput("");
    await sendMessage({ text });
  }, [clearError, isConfigured, isStreaming, sendMessage]);

  const focusSource = useCallback((messageId: string, sourceId: string) => {
    setSelectedActivityMessageId(messageId);
    setActivityOpen(true);
    setSourceFocus((current) => ({
      messageId,
      sourceId,
      nonce: (current?.nonce ?? 0) + 1,
    }));
  }, []);

  const openActivity = useCallback((messageId?: string) => {
    const targetId = messageId ?? activeAssistantMessageId ?? latestAssistantMessage?.id;
    if (targetId) setSelectedActivityMessageId(targetId);
    setSourceFocus(null);
    setActivityOpen(true);
  }, [activeAssistantMessageId, latestAssistantMessage?.id]);

  const closeActivity = useCallback(() => {
    setActivityOpen(false);
  }, []);

  const handleRegenerate = useCallback((messageId: string) => {
    void regenerate({ messageId });
  }, [regenerate]);

  return (
    <section className="main-pane">
      <header className="topbar">
        <div className="topbar__left">
          <button
            aria-label="Open conversation sidebar"
            className="topbar__menu"
            onClick={onOpenSidebar}
            type="button"
          >
            <Menu size={18} />
          </button>
          <div className="topbar__title-wrap">
            <h1 title={conversationTitle ?? "Knowledge Agent"}>{conversationTitle ?? "Knowledge Agent"}</h1>
          </div>
        </div>
        <div className="topbar__actions">
          <button
            aria-label="Open activity and sources"
            aria-pressed={activityOpen}
            className="topbar__activity"
            onClick={() => openActivity()}
            type="button"
          >
            <PanelRight aria-hidden="true" size={15} />
            <span>Activity</span>
            {isStreaming && <LoaderCircle aria-hidden="true" className="topbar__activity-spin" size={12} />}
          </button>
        </div>
      </header>

      <div className={clsx("chat-activity-layout", activityOpen && "chat-activity-layout--open")}>
        <div className="conversation-pane">
          <div
            className="chat-scroll"
            ref={chatScrollRef}
          >
            <div className="chat-inner">
              {messages.length === 0 ? (
                <Welcome onSelect={submit} />
              ) : (
                <MessageList
                  isStreaming={isStreaming}
                  lastMessageId={lastMessage?.id}
                  messages={messages}
                  onActivity={openActivity}
                  onCitation={focusSource}
                  onRegenerate={handleRegenerate}
                  stackRef={messageStackRef}
                />
              )}
            </div>
          </div>

          {error && !hasMessageError && <div className="chat-inner"><div className="error-box">{error.message}</div></div>}
          {!isConfigured && (
            <div className="chat-inner">
              <div className="error-box">Chat is inactive until the BoThesis API URL and request context are configured.</div>
            </div>
          )}
          <ChatComposer
            input={input}
            isConfigured={isConfigured}
            isStreaming={isStreaming}
            onChange={setInput}
            onStop={stop}
            onSubmit={submit}
            textareaRef={textareaRef}
          />
        </div>
        {activityOpen && (
          <>
            <button
              aria-label="Close activity"
              className="activity-panel-overlay"
              onClick={closeActivity}
              type="button"
            />
            <AgentActivityPanel
              isStreaming={selectedActivityIsStreaming}
              message={selectedActivityMessage}
              onClose={closeActivity}
              sourceFocus={
                sourceFocus && sourceFocus.messageId === selectedActivityMessage?.id
                  ? sourceFocus
                  : undefined
              }
            />
          </>
        )}
      </div>
    </section>
  );
}

function MessageList({
  isStreaming,
  lastMessageId,
  messages,
  onActivity,
  onCitation,
  onRegenerate,
  stackRef,
}: {
  isStreaming: boolean;
  lastMessageId?: string;
  messages: ChatMessage[];
  onActivity: (messageId?: string) => void;
  onCitation: (messageId: string, sourceId: string) => void;
  onRegenerate: (messageId: string) => void;
  stackRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="message-stack" ref={stackRef}>
      {messages.map((message) => (
        <MessageView
          isStreaming={isStreaming && message.id === lastMessageId}
          key={message.id}
          message={message}
          onActivity={onActivity}
          onCitation={onCitation}
          onRegenerate={onRegenerate}
        />
      ))}
    </div>
  );
}

const MessageView = memo(function MessageView({
  isStreaming,
  message,
  onActivity,
  onCitation,
  onRegenerate,
}: {
  isStreaming: boolean;
  message: ChatMessage;
  onActivity: (messageId?: string) => void;
  onCitation: (messageId: string, sourceId: string) => void;
  onRegenerate: (messageId: string) => void;
}) {
  const { copy, copied } = useClipboard();
  const text = getMessageText(message);
  const streamError = message.parts.find(
    (part): part is Extract<ChatMessagePart, { type: "data-stream-error" }> => part.type === "data-stream-error",
  );

  if (message.role === "user") {
    return <div className="message-row user" data-chat-role="user"><div className="user-bubble">{text}</div></div>;
  }

  return (
    <div className="message-row assistant">
      <div className="avatar avatar--assistant"><BothesisMark className="bothesis-mark--avatar" label="Assistant" /></div>
      <div className="message-body">
        <AgentExecutionCard
          isStreaming={isStreaming}
          message={message}
          onOpen={() => onActivity(message.id)}
        />
        {text && (
          <div
            className="assistant-content"
            data-latest-assistant-answer={isStreaming ? "true" : undefined}
            onClick={(event) => handleCitationClick(event, message.id, onCitation)}
          >
            <div className="answer-detail"><IncrementalMarkdown isStreaming={isStreaming} text={text} /></div>
            {isStreaming && <span className="streaming-cursor" />}
          </div>
        )}
        {streamError && <div className="error-box">{streamError.data.message}</div>}
        {!isStreaming && (text || streamError) && (
          <div className="answer-footer">
            <div className="assistant-actions" aria-label="Assistant message actions">
              {text && (
                <button aria-label={copied ? "Copied" : "Copy response"} className="assistant-action" onClick={() => void copy(text)} title={copied ? "Copied" : "Copy"} type="button">
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                </button>
              )}
              <button aria-label={streamError ? "Retry response" : "Regenerate response"} className={clsx("assistant-action", streamError && "assistant-action--retry")} onClick={() => onRegenerate(message.id)} title={streamError ? "Retry" : "Regenerate"} type="button">
                <RefreshCw size={14} />
                {streamError && <span>Retry</span>}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

function latestMessageId(messages: ChatMessage[], role: ChatMessage["role"]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === role) return messages[index]?.id;
  }
  return undefined;
}

function reserveActiveTurnSpace(scroller: HTMLDivElement, stack: HTMLDivElement) {
  const reservedHeight = Math.max(240, scroller.clientHeight - 96);
  stack.style.setProperty("--chat-active-fill", `${reservedHeight}px`);
}

function handleCitationClick(
  event: MouseEvent<HTMLDivElement>,
  messageId: string,
  onCitation: (messageId: string, sourceId: string) => void,
) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const link = target.closest<HTMLAnchorElement>('a[href^="#source-"]');
  const href = link?.getAttribute("href");
  if (!href) return;
  event.preventDefault();
  try {
    onCitation(messageId, decodeURIComponent(href.slice("#source-".length)));
  } catch {
    // Ignore malformed local citation anchors.
  }
}

function ChatComposer({
  input,
  isConfigured,
  isStreaming,
  onChange,
  onStop,
  onSubmit,
  textareaRef,
}: {
  input: string;
  isConfigured: boolean;
  isStreaming: boolean;
  onChange: (value: string) => void;
  onStop: () => void;
  onSubmit: (text: string) => Promise<void>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(input);
  };
  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        <button aria-label="Attachments are not available" className="composer-tool" disabled title="Attachments are not available yet" type="button">
          <Plus size={15} />
        </button>
        <textarea
          aria-label="Message assistant"
          disabled={isStreaming || !isConfigured}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void onSubmit(input);
            }
          }}
          placeholder="Ask about reports, risks, metrics, or decisions..."
          ref={textareaRef}
          rows={1}
          value={input}
        />
        <button
          aria-label={isStreaming ? "Stop generating" : "Send message"}
          className={clsx("composer-send", isStreaming && "composer-send--stop")}
          disabled={!isStreaming && (!input.trim() || !isConfigured)}
          onClick={isStreaming ? onStop : undefined}
          type={isStreaming ? "button" : "submit"}
        >
          {isStreaming ? <Square className="composer-send__stop-icon" size={11} strokeWidth={0} /> : <Send className="composer-send__send-icon" size={18} />}
        </button>
      </form>
    </div>
  );
}

function Welcome({ onSelect }: { onSelect: (text: string) => Promise<void> }) {
  return (
    <div className="welcome">
      <div className="welcome__content">
        <div className="welcome-heading">
          <BothesisMark className="bothesis-mark--welcome" decorative />
          <div><p className="welcome-eyebrow">Enterprise assistant</p><h2>How can I help?</h2></div>
        </div>
        <p className="welcome-copy">Ask a question, request a summary, or draft a decision memo from knowledge you can access.</p>
        <div className="suggestions">
          {suggestions.map((suggestion) => (
            <button className="suggestion" key={suggestion.title} onClick={() => void onSelect(suggestion.prompt)} type="button">
              <span className="suggestion__icon"><suggestion.icon size={17} /></span>
              <span className="suggestion__copy"><span className="suggestion__title">{suggestion.title}</span><span className="suggestion__description">{suggestion.description}</span></span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
