"use client";

import clsx from "clsx";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  FileUp,
  LibraryBig,
  LoaderCircle,
  Plus,
  Send,
  Square,
  X,
} from "lucide-react";
import {
  type FormEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

import { appBrand } from "@/lib/brand";
import { useAuthPrompt } from "@/components/auth/AuthPrompt";
import { isGuestSession } from "@/lib/auth/session";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { type Collection, listCollections } from "../api";
import type { ConversationDocument } from "../types";
import { FileTypeIcon } from "./ResourceIcon";

const ACCEPTED_FILES = ".avif,.bmp,.csv,.docx,.gif,.htm,.html,.jpeg,.jpg,.json,.jsonl,.log,.markdown,.md,.pdf,.png,.pptx,.rst,.sql,.tif,.tiff,.tsv,.txt,.webp,.xlsx,.xml,.yaml,.yml";

export interface ComposerAttachment {
  key: string;
  fileName: string;
  sizeBytes: number;
  progress: "starting" | "uploading" | "validating" | "ready" | "failed";
  document?: ConversationDocument;
  error?: string;
}

interface ChatComposerProps {
  attachments: ComposerAttachment[];
  contextCollections: Collection[];
  enterToSend: boolean;
  input: string;
  isConfigured: boolean;
  isStreaming: boolean;
  isUploading: boolean;
  onChange: (value: string) => void;
  onContextCollectionsChange: (collections: Collection[]) => void;
  onFiles: (files: FileList) => void;
  onRemoveAttachment: (key: string) => void;
  onStop: () => void;
  onSubmit: (text: string) => Promise<void>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

/** The one responsive composer for ordinary and inspector chat widths. */
export function ChatComposer({
  attachments,
  contextCollections,
  enterToSend,
  input,
  isConfigured,
  isStreaming,
  isUploading,
  onChange,
  onContextCollectionsChange,
  onFiles,
  onRemoveAttachment,
  onStop,
  onSubmit,
  textareaRef,
}: ChatComposerProps) {
  const { requestSignIn } = useAuthPrompt();
  const session = useAuthSession();
  const [addOpen, setAddOpen] = useState(false);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsError, setCollectionsError] = useState<string>();
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [collectionsRequested, setCollectionsRequested] = useState(false);
  const [collectionsExpanded, setCollectionsExpanded] = useState(false);
  const [showAllCollections, setShowAllCollections] = useState(false);
  const addButtonRef = useRef<HTMLButtonElement | null>(null);
  const addPopoverRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!addOpen || collections.length || collectionsLoading || collectionsRequested) return;
    const controller = new AbortController();
    setCollectionsRequested(true);
    setCollectionsLoading(true);
    setCollectionsError(undefined);
    void listCollections(controller.signal)
      .then((items) => setCollections(items))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setCollectionsError(cause instanceof Error ? cause.message : "Could not load your collections.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setCollectionsLoading(false);
      });
    return () => controller.abort();
  }, [addOpen, collections.length, collectionsLoading, collectionsRequested]);

  useEffect(() => {
    if (!addOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAddOpen(false);
      addButtonRef.current?.focus();
    };
    const closeOnOutsidePress = (event: PointerEvent) => {
      const target = event.target as Node;
      if (addPopoverRef.current?.contains(target) || addButtonRef.current?.contains(target)) return;
      setAddOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("pointerdown", closeOnOutsidePress);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("pointerdown", closeOnOutsidePress);
    };
  }, [addOpen]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit(input);
  };
  const toggleCollection = (collection: Collection) => {
    const selected = contextCollections.some((item) => item.id === collection.id);
    onContextCollectionsChange(
      selected
        ? contextCollections.filter((item) => item.id !== collection.id)
        : [...contextCollections, collection],
    );
  };
  const displayedCollections = showAllCollections ? collections : collections.slice(0, 3);
  const revealCollections = () => setCollectionsExpanded(true);

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        {(attachments.length > 0 || contextCollections.length > 0) && (
          <div className="composer-attachments">
            {contextCollections.map((collection) => (
              <span className="composer-attachment composer-attachment--collection" key={collection.id}>
                <LibraryBig aria-hidden="true" size={14} />
                <span>{collection.title}</span>
                <small>Collection</small>
                <button
                  aria-label={`Remove ${collection.title}`}
                  onClick={() => onContextCollectionsChange(
                    contextCollections.filter((item) => item.id !== collection.id),
                  )}
                  type="button"
                >
                  <X aria-hidden="true" size={12} />
                </button>
              </span>
            ))}
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
                  ? <LoaderCircle aria-hidden="true" className="composer-attachment__spin" size={14} />
                  : <FileTypeIcon name={item.fileName} />}
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
          accept={ACCEPTED_FILES}
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
          aria-label="Message BoThesis"
          autoComplete="off"
          disabled={!isConfigured}
          name="message"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (enterToSend && event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
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
          <span className="composer-add">
            <button
              aria-expanded={addOpen}
              aria-haspopup="dialog"
              className="composer-tool"
              disabled={!isConfigured}
              onClick={() => setAddOpen((open) => !open)}
              ref={addButtonRef}
              type="button"
            >
              <Plus aria-hidden="true" size={16} />
              <span>Add</span>
            </button>
            {addOpen && (
              <div aria-label="Add context" className="composer-add-popover" ref={addPopoverRef} role="dialog">
                <div className="composer-add-popover__header">
                  <div>
                    <p>Add context</p>
                    <span>Attach a collection or a file to this turn.</span>
                  </div>
                  <button aria-label="Close add context" onClick={() => setAddOpen(false)} type="button">
                    <X aria-hidden="true" size={14} />
                  </button>
                </div>
                <div className="composer-add-popover__actions">
                  <button
                    className="composer-add-popover__row"
                    disabled={attachments.length >= 12}
                    onClick={() => {
                      if (isGuestSession(session)) {
                        setAddOpen(false);
                        requestSignIn("Sign in to upload a private file into this conversation.");
                        return;
                      }
                      fileInputRef.current?.click();
                    }}
                    type="button"
                  >
                    <FileUp aria-hidden="true" size={16} />
                    <span>Upload file</span>
                  </button>
                  <button
                    aria-controls="chat-context-collections"
                    aria-expanded={collectionsExpanded}
                    className="composer-add-popover__row"
                    onClick={revealCollections}
                    type="button"
                  >
                    <LibraryBig aria-hidden="true" size={16} />
                    <span>Choose from collection</span>
                    <ChevronRight aria-hidden="true" className="composer-add-popover__row-caret" size={16} />
                  </button>
                  <button
                    aria-controls="chat-context-collections"
                    aria-expanded={collectionsExpanded && !showAllCollections}
                    className="composer-add-popover__row"
                    onClick={() => {
                      setCollectionsExpanded(true);
                      setShowAllCollections(false);
                    }}
                    type="button"
                  >
                    <LibraryBig aria-hidden="true" size={16} />
                    <span>Recent collections</span>
                    <ChevronRight aria-hidden="true" className="composer-add-popover__row-caret" size={16} />
                  </button>
                  <button
                    aria-controls="chat-context-collections"
                    aria-expanded={collectionsExpanded && showAllCollections}
                    className="composer-add-popover__row"
                    onClick={() => {
                      setCollectionsExpanded(true);
                      setShowAllCollections(true);
                    }}
                    type="button"
                  >
                    <LibraryBig aria-hidden="true" size={16} />
                    <span>Browse all collections</span>
                    <ChevronRight aria-hidden="true" className="composer-add-popover__row-caret" size={16} />
                  </button>
                </div>
                {collectionsExpanded && (
                  <div className="composer-add-popover__collections" id="chat-context-collections">
                    <div className="composer-add-popover__section-title">
                      <span>{showAllCollections ? "All collections" : "Recent collections"}</span>
                      {collectionsLoading && <LoaderCircle aria-label="Loading collections" className="composer-attachment__spin" size={14} />}
                    </div>
                    {collectionsError ? (
                      <div className="composer-add-popover__error" role="alert">
                        <p>{collectionsError}</p>
                        <button onClick={() => setCollectionsRequested(false)} type="button">Retry collections</button>
                      </div>
                    ) : displayedCollections.length ? (
                      <ul>
                        {displayedCollections.map((collection) => {
                          const selected = contextCollections.some((item) => item.id === collection.id);
                          return (
                            <li key={collection.id}>
                              <button
                                aria-pressed={selected}
                                className={clsx(selected && "is-selected")}
                                onClick={() => toggleCollection(collection)}
                                type="button"
                              >
                                <LibraryBig aria-hidden="true" size={16} />
                                <span>{collection.title}</span>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    ) : !collectionsLoading ? (
                      <p className="composer-add-popover__empty">No collections are available to your account.</p>
                    ) : null}
                  </div>
                )}
              </div>
            )}
          </span>
          <span className="composer-context-indicator composer-context-indicator--knowledge"><LibraryBig aria-hidden="true" size={14} />Knowledge: Company</span>
          <span className="composer-context-indicator"><Bot aria-hidden="true" size={14} />BoThesis</span>
          <span className="composer-context-indicator composer-context-indicator--model">Managed model <ChevronDown aria-hidden="true" size={14} /></span>
          <span className="composer__shortcut">
            {enterToSend ? "Enter to send · Shift + Enter for new line" : "Use the send button · Enter for new line"}
          </span>
          <button
            aria-label={isStreaming ? "Stop generating" : "Send message"}
            className={clsx("composer-send", isStreaming && "composer-send--stop")}
            disabled={!isStreaming && (
              isUploading
              || (!input.trim() && !attachments.some((item) => item.progress === "ready"))
              || !isConfigured
            )}
            onClick={isStreaming ? onStop : undefined}
            type={isStreaming ? "button" : "submit"}
          >
            {isStreaming ? <Square aria-hidden="true" className="composer-send__stop-icon" size={12} strokeWidth={0} /> : <Send aria-hidden="true" className="composer-send__send-icon" size={16} />}
          </button>
        </div>
      </form>
      <p className="composer-disclaimer" id="composer-help">{appBrand.productName} can make mistakes. Verify important decisions with the cited sources.</p>
    </div>
  );
}

function attachmentProgressLabel(item: ComposerAttachment) {
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
