"use client";

import clsx from "clsx";
import {
  BarChart3,
  Check,
  Copy,
  FileSearch,
  ArrowDown,
  FilePenLine,
  ListChecks,
  LoaderCircle,
  Menu,
  Paperclip,
  RefreshCw,
  Send,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";
import { memo, type FormEvent, type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useClipboard } from "@/lib/hooks/useClipboard";
import { AppShell } from "@/components/ui/AppShell";
import { ProductMark } from "@/components/ui/ProductMark";
import { getBothesisChatConfiguration } from "@/lib/api/config";
import {
  getAvailableChatConnectors,
  releaseConversationDocument,
  uploadConversationDocument,
} from "@/modules/chat/api";
import { connectorDefinition } from "@/modules/connectors/catalog";
import { PluginPicker } from "@/modules/connectors/components/PluginPicker";
import { SelectedPluginChips } from "@/modules/connectors/components/SelectedPluginChips";
import type { ChatConnector, ChatConnectorMode } from "@/modules/connectors/types";
import {
  cachedToUIMessage,
  conversationAdapter,
  getMessageText,
  setConversationUser,
  titleFromMessage,
  uiToCachedMessage,
} from "@/modules/chat/conversations";
import { useBothesisChat } from "@/modules/chat/hooks/useBothesisChat";
import { useJumpToLatest } from "@/modules/chat/hooks/useJumpToLatest";
import { useSidebarState } from "@/modules/chat/hooks/useSidebarState";
import type {
  ChatConversation,
  ChatMessage,
  ChatMessagePart,
  ConversationDocument,
} from "@/modules/chat/types";
import { AppSidebar } from "./AppSidebar";
import { AnswerSources } from "./AnswerSources";
import { AssistantTurn } from "./AssistantTurn";

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
    icon: FilePenLine,
  },
  {
    title: "Source lookup",
    description: "Find policy details, owners, and referenced documents.",
    prompt: "Find policy details related to internal permissions and cite the source documents.",
    icon: ListChecks,
  },
];

interface ComposerDocument {
  key: string;
  fileName: string;
  sizeBytes: number;
  progress: "starting" | "uploading" | "validating" | "ready" | "failed";
  document?: ConversationDocument;
  error?: string;
}

function createDraftConversationId() {
  return globalThis.crypto.randomUUID();
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
    const storedMessages = await conversationAdapter.getConversationMessages(id);
    const documentIds = new Set(
      storedMessages.flatMap((message) => message.parts.flatMap((part) => (
        part.type === "data-document" ? [part.data.id] : []
      ))),
    );
    await Promise.allSettled(
      [...documentIds].map((documentId) => (
        releaseConversationDocument(documentId)
      )),
    );
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
    <AppShell
      sidebar={<AppSidebar
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
      />}
    >
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
    </AppShell>
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
  const [composerAttachments, setComposerAttachments] = useState<ComposerDocument[]>([]);
  const [connectors, setConnectors] = useState<ChatConnector[]>([]);
  const [connectorsError, setConnectorsError] = useState<string | null>(null);
  const [connectorsLoading, setConnectorsLoading] = useState(true);
  const [connectorMode, setConnectorMode] = useState<ChatConnectorMode>("auto");
  const [selectedConnectorIds, setSelectedConnectorIds] = useState<string[]>([]);
  const [connectorRevision, setConnectorRevision] = useState(0);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const messageStackRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const uploadControllersRef = useRef(new Map<string, AbortController>());
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
  const hasMessageError = messages.some((message) => message.turn?.status === "failed");
  const isUploading = composerAttachments.some((item) => (
    item.progress !== "ready" && item.progress !== "failed"
  ));
  const selectedConnectors = connectors.filter((connector) => selectedConnectorIds.includes(connector.id));
  const activeConnectorLabel = connectorMode === "selected"
    ? selectedConnectors.length === 1
      ? connectorDefinition(selectedConnectors[0]?.provider ?? "")?.name ?? selectedConnectors[0]?.display_name
      : selectedConnectors.length > 1 ? "selected sources" : undefined
    : connectorMode === "auto" ? "permitted knowledge" : undefined;

  useEffect(() => {
    if (!isConfigured) {
      setConnectorsLoading(false);
      return;
    }
    const controller = new AbortController();
    setConnectorsLoading(true);
    setConnectorsError(null);
    getAvailableChatConnectors(controller.signal)
      .then((items) => {
        setConnectors(items);
        setSelectedConnectorIds((current) => current.filter((id) => items.some((item) => item.id === id)));
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setConnectorsError(cause instanceof Error ? cause.message : "Could not load permitted connectors.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setConnectorsLoading(false);
      });
    return () => controller.abort();
  }, [connectorRevision, isConfigured]);

  useEffect(() => () => {
    for (const controller of uploadControllersRef.current.values()) controller.abort();
    uploadControllersRef.current.clear();
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [input]);

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
    const readyDocuments = composerAttachments
      .flatMap((item) => item.document ? [item.document] : []);
    const text = value.trim() || (readyDocuments.length
      ? "Please analyze the attached file."
      : "");
    if (!text || isUploading || isStreaming || !isConfigured || connectorMode === "selected" && !selectedConnectorIds.length) return;
    clearError();
    setInput("");
    setComposerAttachments([]);
    await sendMessage({
      text,
      documents: readyDocuments,
      connectorMode,
      connectorIds: selectedConnectorIds,
    });
  }, [
    clearError,
    composerAttachments,
    isConfigured,
    isStreaming,
    isUploading,
    connectorMode,
    selectedConnectorIds,
    sendMessage,
  ]);

  const selectAttachments = useCallback((files: FileList) => {
    const availableSlots = Math.max(0, 12 - composerAttachments.length);
    for (const file of Array.from(files).slice(0, availableSlots)) {
      const key = `${file.name}:${file.size}:${file.lastModified}:${Math.random().toString(36).slice(2)}`;
      const controller = new AbortController();
      uploadControllersRef.current.set(key, controller);
      setComposerAttachments((current) => [...current, {
        key,
        fileName: file.name,
        sizeBytes: file.size,
        progress: "starting",
      }]);
      void uploadConversationDocument(file, {
        signal: controller.signal,
        onProgress: (progress) => setComposerAttachments((current) => (
          current.map((item) => item.key === key ? { ...item, progress } : item)
        )),
      }).then((document) => {
        setComposerAttachments((current) => current.map((item) => (
          item.key === key ? { ...item, document, progress: "ready" } : item
        )));
      }).catch((cause) => {
        if (controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : "Document upload failed.";
        setComposerAttachments((current) => current.map((item) => (
          item.key === key ? { ...item, error: message, progress: "failed" } : item
        )));
      }).finally(() => {
        uploadControllersRef.current.delete(key);
      });
    }
  }, [composerAttachments.length]);

  const removeAttachment = useCallback((key: string) => {
    const item = composerAttachments.find((candidate) => candidate.key === key);
    uploadControllersRef.current.get(key)?.abort();
    uploadControllersRef.current.delete(key);
    setComposerAttachments((current) => current.filter((candidate) => candidate.key !== key));
    if (item?.document) {
      void releaseConversationDocument(item.document.id);
    }
  }, [composerAttachments]);

  const handleRegenerate = useCallback((messageId: string) => {
    void regenerate({ messageId, connectorMode, connectorIds: selectedConnectorIds });
  }, [connectorMode, regenerate, selectedConnectorIds]);

  const { hasMoreBelow, jumpToLatest } = useJumpToLatest(chatScrollRef, messageStackRef);

  return (
    <section className="main-pane" id="main-content">
      <header className="topbar">
        <div className="topbar__left">
          <button
            aria-label="Open conversation sidebar"
            className="topbar__menu"
            onClick={onOpenSidebar}
            type="button"
          >
            <Menu aria-hidden="true" size={18} />
          </button>
          <div className="topbar__title-wrap">
            <span className="topbar__identity-mark"><ProductMark decorative size="sm" /></span>
            <span className="topbar__title-copy">
              <span className="topbar__eyebrow">Knowledge assistant</span>
              <h1 title={conversationTitle ?? "New conversation"}>{conversationTitle ?? "New conversation"}</h1>
            </span>
          </div>
        </div>
      </header>

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
                  activityConnectorLabel={activeConnectorLabel}
                  isStreaming={isStreaming}
                  lastMessageId={lastMessage?.id}
                  messages={messages}
                  onRegenerate={handleRegenerate}
                  stackRef={messageStackRef}
                />
              )}
            </div>
          </div>

          {hasMoreBelow && messages.length > 0 && (
            <button
              aria-label="Jump to latest"
              className="chat-jump"
              onClick={jumpToLatest}
              title="Jump to latest"
              type="button"
            >
              <ArrowDown aria-hidden="true" size={15} />
            </button>
          )}

          {error && !hasMessageError && <div className="chat-inner"><div className="error-box" role="alert">{error.message} Try again or start a new conversation.</div></div>}
          {!isConfigured && (
            <div className="chat-inner">
              <div className="error-box" role="status">Chat is unavailable because workspace access has not been configured. Contact your administrator.</div>
            </div>
          )}
          <ChatComposer
            attachments={composerAttachments}
            connectorMode={connectorMode}
            connectors={connectors}
            connectorsError={connectorsError}
            connectorsLoading={connectorsLoading}
            input={input}
            isConfigured={isConfigured}
            isStreaming={isStreaming}
            isUploading={isUploading}
            onChange={setInput}
            onConnectorModeChange={setConnectorMode}
            onConnectorReload={() => setConnectorRevision((value) => value + 1)}
            onConnectorSelectionChange={setSelectedConnectorIds}
            onFiles={selectAttachments}
            onRemoveAttachment={removeAttachment}
            onStop={stop}
            onSubmit={submit}
            selectedConnectorIds={selectedConnectorIds}
            textareaRef={textareaRef}
          />
      </div>
    </section>
  );
}

function MessageList({
  activityConnectorLabel,
  isStreaming,
  lastMessageId,
  messages,
  onRegenerate,
  stackRef,
}: {
  activityConnectorLabel?: string;
  isStreaming: boolean;
  lastMessageId?: string;
  messages: ChatMessage[];
  onRegenerate: (messageId: string) => void;
  stackRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="message-stack" ref={stackRef}>
      {messages.map((message) => (
        <MessageView
          activityConnectorLabel={isStreaming && message.id === lastMessageId ? activityConnectorLabel : undefined}
          isStreaming={isStreaming && message.id === lastMessageId}
          key={message.id}
          message={message}
          onRegenerate={onRegenerate}
        />
      ))}
    </div>
  );
}

const MessageView = memo(function MessageView({
  activityConnectorLabel,
  isStreaming,
  message,
  onRegenerate,
}: {
  activityConnectorLabel?: string;
  isStreaming: boolean;
  message: ChatMessage;
  onRegenerate: (messageId: string) => void;
}) {
  const { copy, copied } = useClipboard();
  // The answer keeps easing onto screen for a moment after the stream ends, so
  // the sources and the action row wait for the text rather than for the socket.
  const [isRevealing, setIsRevealing] = useState(false);
  const hasSettled = !isStreaming && !isRevealing;
  const text = getMessageText(message);
  const streamError = message.turn?.error;
  const messageDocuments = message.parts
    .filter((part): part is Extract<ChatMessagePart, { type: "data-document" }> => (
      part.type === "data-document"
    ));

  if (message.role === "user") {
    return (
      <div className="message-row user" data-chat-role="user">
        <div className="user-bubble">
          {messageDocuments.length > 0 && (
            <div className="message-attachments">
              {messageDocuments.map((part) => (
                <span className="message-attachment" key={part.data.id}>
                  <FileSearch aria-hidden="true" size={13} />
                  <span title={part.data.fileName}>{part.data.fileName}</span>
                </span>
              ))}
            </div>
          )}
          {text && <span>{text}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="message-row assistant">
      <div className="message-body">
        <AssistantTurn
          activityConnectorLabel={activityConnectorLabel}
          isStreaming={isStreaming}
          onRevealingChange={setIsRevealing}
          turn={message.turn}
        />
        {streamError && <div className="error-box" role="alert">{streamError}</div>}
        {hasSettled && <AnswerSources turn={message.turn} />}
        {hasSettled && (text || streamError) && (
          <div className="answer-footer">
            <div className="assistant-actions" aria-label="Assistant message actions" role="group">
              {text && (
                <button aria-label={copied ? "Copied" : "Copy response"} className="assistant-action" onClick={() => void copy(text)} title={copied ? "Copied" : "Copy"} type="button">
                  {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
                </button>
              )}
              <button aria-label={streamError ? "Retry response" : "Regenerate response"} className={clsx("assistant-action", streamError && "assistant-action--retry")} onClick={() => onRegenerate(message.id)} title={streamError ? "Retry" : "Regenerate"} type="button">
                <RefreshCw aria-hidden="true" size={14} />
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

function ChatComposer({
  attachments,
  connectorMode,
  connectors,
  connectorsError,
  connectorsLoading,
  input,
  isConfigured,
  isStreaming,
  isUploading,
  onChange,
  onConnectorModeChange,
  onConnectorReload,
  onConnectorSelectionChange,
  onFiles,
  onRemoveAttachment,
  onStop,
  onSubmit,
  selectedConnectorIds,
  textareaRef,
}: {
  attachments: ComposerDocument[];
  connectorMode: ChatConnectorMode;
  connectors: ChatConnector[];
  connectorsError: string | null;
  connectorsLoading: boolean;
  input: string;
  isConfigured: boolean;
  isStreaming: boolean;
  isUploading: boolean;
  onChange: (value: string) => void;
  onConnectorModeChange: (mode: ChatConnectorMode) => void;
  onConnectorReload: () => void;
  onConnectorSelectionChange: (ids: string[]) => void;
  onFiles: (files: FileList) => void;
  onRemoveAttachment: (key: string) => void;
  onStop: () => void;
  onSubmit: (text: string) => Promise<void>;
  selectedConnectorIds: string[];
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(input);
  };
  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        {connectorMode === "selected" && (
          <SelectedPluginChips
            connectors={connectors.filter((connector) => selectedConnectorIds.includes(connector.id))}
            onRemove={(connectorId) => onConnectorSelectionChange(selectedConnectorIds.filter((id) => id !== connectorId))}
          />
        )}
        {attachments.length > 0 && (
          <div className="composer-attachments">
            {attachments.map((item) => (
              <span
                className={clsx(
                  "composer-attachment",
                  item.progress === "failed" && "composer-attachment--failed",
                )}
                key={item.key}
                title={item.error ?? item.fileName}
              >
                {item.progress !== "ready" && item.progress !== "failed"
                  ? <LoaderCircle aria-hidden="true" className="composer-attachment__spin" size={13} />
                  : <FileSearch aria-hidden="true" size={13} />}
                <span>{item.fileName}</span>
                <small>{attachmentProgressLabel(item)}</small>
                <button
                  aria-label={`Remove ${item.fileName}`}
                  onClick={() => onRemoveAttachment(item.key)}
                  type="button"
                >
                  <X aria-hidden="true" size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
        <input
          accept=".avif,.bmp,.csv,.docx,.gif,.htm,.html,.jpeg,.jpg,.json,.jsonl,.log,.markdown,.md,.pdf,.png,.pptx,.rst,.sql,.tif,.tiff,.tsv,.txt,.webp,.xlsx,.xml,.yaml,.yml"
          hidden
          multiple
          onChange={(event) => {
            if (event.target.files?.length) onFiles(event.target.files);
            event.target.value = "";
          }}
          ref={fileInputRef}
          type="file"
        />
        <textarea
          aria-describedby="composer-help"
          aria-label="Message assistant"
          autoComplete="off"
          disabled={!isConfigured}
          name="message"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void onSubmit(input);
            }
          }}
          placeholder="Ask about your company knowledge…"
          ref={textareaRef}
          rows={1}
          value={input}
        />
        <div className="composer__footer">
          <button
            aria-label="Attach files"
            className="composer-tool"
            disabled={!isConfigured || attachments.length >= 12}
            onClick={() => fileInputRef.current?.click()}
            title="Attach files"
            type="button"
          >
            <Paperclip aria-hidden="true" size={15} />
            <span>Attach</span>
          </button>
          <PluginPicker
            connectors={connectors}
            disabled={!isConfigured || isStreaming}
            error={connectorsError}
            loading={connectorsLoading}
            mode={connectorMode}
            onModeChange={onConnectorModeChange}
            onReload={onConnectorReload}
            onSelectionChange={onConnectorSelectionChange}
            selectedIds={selectedConnectorIds}
          />
          <span className="composer__privacy"><ShieldCheck aria-hidden="true" size={13} /> Permission-aware</span>
          <span className="composer__shortcut">Enter to send · Shift + Enter for new line</span>
          <button
            aria-label={isStreaming ? "Stop generating" : "Send message"}
            className={clsx("composer-send", isStreaming && "composer-send--stop")}
            disabled={!isStreaming && (
              isUploading
              || (!input.trim() && !attachments.some((item) => item.progress === "ready"))
              || !isConfigured
              || connectorMode === "selected" && !selectedConnectorIds.length
            )}
            onClick={isStreaming ? onStop : undefined}
            type={isStreaming ? "button" : "submit"}
          >
            {isStreaming ? <Square aria-hidden="true" className="composer-send__stop-icon" size={11} strokeWidth={0} /> : <Send aria-hidden="true" className="composer-send__send-icon" size={17} />}
          </button>
        </div>
      </form>
      <p className="composer-disclaimer" id="composer-help">BoThesis can make mistakes. Verify important decisions with the cited sources.</p>
    </div>
  );
}

function attachmentProgressLabel(item: ComposerDocument) {
  if (item.progress === "starting") return "Starting…";
  if (item.progress === "uploading") return "Uploading…";
  if (item.progress === "validating") return "Validating…";
  if (item.progress === "failed") return "Failed";
  return formatFileSize(item.sizeBytes);
}

function formatFileSize(sizeBytes: number) {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${Math.ceil(sizeBytes / 1024)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Welcome({ onSelect }: { onSelect: (text: string) => Promise<void> }) {
  return (
    <div className="welcome">
      <div className="welcome__content">
        <div className="welcome-hero">
          <span className="welcome-hero__mark"><ProductMark decorative size="lg" /></span>
          <div className="welcome-identity">
            BoThesis workspace
          </div>
          <div className="welcome-heading">
            <h2>What can I help you understand?</h2>
          </div>
          <p className="welcome-copy">Ask across the company knowledge you can access, compare business signals, or turn trusted context into a clear next step.</p>
          <div className="welcome-trust" aria-label="Assistant capabilities">
            <span><ShieldCheck aria-hidden="true" size={14} /> Searches only content you can access</span>
            <span><FileSearch aria-hidden="true" size={14} /> Keeps evidence with every answer</span>
          </div>
        </div>
        <p className="suggestions__label">Try a starting point</p>
        <div className="suggestions">
          {suggestions.map((suggestion) => (
            <button className="suggestion" key={suggestion.title} onClick={() => void onSelect(suggestion.prompt)} type="button">
              <span className="suggestion__icon"><suggestion.icon aria-hidden="true" size={17} /></span>
              <span className="suggestion__copy"><span className="suggestion__title">{suggestion.title}</span><span className="suggestion__description">{suggestion.description}</span></span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
