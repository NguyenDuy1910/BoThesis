"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { ConversationRow, SearchField } from "@/components/patterns";
import { RailCaption, RailGroup } from "@/components/rails";
import type { ChatConversation } from "@/modules/chat/types";
import { ConversationActionsMenu } from "./ConversationActionsMenu";

interface ChatSidebarContentProps {
  collapsed: boolean;
  conversations: ChatConversation[];
  activeId: string | null;
  isLoading: boolean;
  onSelectConversation: (id: string) => void;
  onRenameConversation: (id: string, title: string) => void | Promise<void>;
  onDeleteConversation: (id: string) => void | Promise<void>;
  searchRequested?: boolean;
  onSearchRequestHandled?: () => void;
}

/** The chat-specific part of the persistent product rail. */
export function ChatSidebarContent({
  collapsed,
  conversations,
  activeId,
  isLoading,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  searchRequested = false,
  onSearchRequestHandled,
}: ChatSidebarContentProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  useEffect(() => {
    if (!collapsed) return;
    setSearchOpen(false);
    setSearchQuery("");
  }, [collapsed]);

  useEffect(() => {
    if (!searchRequested) return;
    setSearchOpen(true);
    onSearchRequestHandled?.();
  }, [onSearchRequestHandled, searchRequested]);

  return (
    <>
      <SidebarChatSearch
        collapsed={collapsed}
        onSearchChange={setSearchQuery}
        searchOpen={searchOpen}
        searchQuery={searchQuery}
        setSearchOpen={setSearchOpen}
      />

      <RecentChatList
        collapsed={collapsed}
        conversations={conversations}
        activeId={activeId}
        isLoading={isLoading}
        searchQuery={searchQuery}
        onSelect={onSelectConversation}
        onRename={onRenameConversation}
        onDelete={onDeleteConversation}
      />
    </>
  );
}

function SidebarChatSearch({
  collapsed,
  onSearchChange,
  searchOpen,
  searchQuery,
  setSearchOpen,
}: {
  collapsed: boolean;
  onSearchChange: (value: string) => void;
  searchOpen: boolean;
  searchQuery: string;
  setSearchOpen: (open: boolean) => void;
}) {
  if (collapsed || !searchOpen) return null;

  return (
    <section aria-label="Search chats" className="flex items-center gap-1 px-3 pb-1">
      <SearchField
        autoFocus
        className="min-w-0 flex-1"
        onChange={onSearchChange}
        placeholder="Search recent chats"
        value={searchQuery}
      />
      <button
        aria-label="Close conversation search"
        className="grid h-7 w-7 shrink-0 place-items-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        onClick={() => {
          onSearchChange("");
          setSearchOpen(false);
        }}
        type="button"
      >
        <X aria-hidden="true" size={15} />
      </button>
    </section>
  );
}

const SKELETON_WIDTHS = ["75%", "90%", "68%", "82%", "72%"];

function SkeletonRows() {
  return (
    <div className="grid gap-2 px-3 py-1">
      {SKELETON_WIDTHS.map((width, i) => (
        <div
          key={i}
          className="h-3 animate-pulse rounded-full bg-[var(--border-default)]"
          style={{ width }}
        />
      ))}
    </div>
  );
}

function RecentChatList({
  collapsed,
  conversations,
  activeId,
  isLoading,
  onSelect,
  onRename,
  onDelete,
  searchQuery,
}: {
  collapsed: boolean;
  conversations: ChatConversation[];
  activeId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void | Promise<void>;
  onDelete: (id: string) => void | Promise<void>;
  searchQuery: string;
}) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [renameTarget, setRenameTarget] = useState<ChatConversation | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ChatConversation | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [savingRename, setSavingRename] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const matchingConversations = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase();
    if (!query) return conversations;
    return conversations.filter((conversation) => (
      formatConversationTitle(conversation.title).toLocaleLowerCase().includes(query)
    ));
  }, [conversations, searchQuery]);
  const groupedConversations = useMemo(
    () => groupConversations(matchingConversations),
    [matchingConversations],
  );
  const hasConversations = matchingConversations.length > 0;
  useEffect(() => setOpenMenuId(null), [collapsed]);

  if (collapsed) return null;

  return (
    <div className="min-h-0" onScroll={() => setOpenMenuId(null)}>
        {isLoading ? (
          collapsed ? null : <SkeletonRows />
        ) : !hasConversations ? (
          !collapsed && (
            <div className="grid gap-1 px-5 py-6 text-center text-[length:var(--text-size-ui)] text-[var(--text-tertiary)]">
              <span className="mx-auto mb-1 grid h-7 w-7 place-items-center rounded-[var(--radius-sm)] bg-[var(--accent-soft)] text-[var(--text-accent)]">
                <MessageSquare aria-hidden="true" size={16} />
              </span>
              <strong className="text-[var(--text-secondary)]">{searchQuery ? "No matching chats" : "Start a conversation"}</strong>
              <span>
                {searchQuery
                  ? "Try another search term."
                  : "Your conversations will appear here."}
              </span>
            </div>
          )
        ) : (
          groupedConversations.map((group) => {
            if (group.items.length === 0) return null;
            return (
              <div className="grid gap-0.5" key={group.label}>
                <RailCaption collapsed={collapsed}>{group.label}</RailCaption>
                <RailGroup>
                  {group.items.map((conversation) => {
                    const displayTitle = formatConversationTitle(conversation.title);
                    return (
                      <ConversationRow
                        actions={
                          <ConversationActionsMenu
                            conversationTitle={displayTitle}
                            deleting={deletingIds.has(conversation.id)}
                            onDelete={() => {
                              setOpenMenuId(null);
                              setActionError(null);
                              setDeleteTarget(conversation);
                            }}
                            onOpenChange={(open) => {
                              setOpenMenuId((current) =>
                                open
                                  ? conversation.id
                                  : current === conversation.id
                                    ? null
                                    : current,
                              );
                            }}
                            onRename={() => {
                              setOpenMenuId(null);
                              setActionError(null);
                              setRenameTarget(conversation);
                              setRenameValue(conversation.title);
                            }}
                            open={openMenuId === conversation.id}
                          />
                        }
                        active={conversation.id === activeId}
                        key={conversation.id}
                        onSelect={() => {
                          setOpenMenuId(null);
                          onSelect(conversation.id);
                        }}
                        title={displayTitle}
                      />
                    );
                  })}
                </RailGroup>
              </div>
            );
          })
        )}

      <Dialog
        className="max-w-sm"
        initialFocusRef={renameInputRef}
        onClose={() => {
          if (!savingRename) setRenameTarget(null);
        }}
        open={Boolean(renameTarget)}
        title="Rename conversation"
      >
        <form
          id="rename-conversation-form"
          onSubmit={async (event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const nextTitle = renameValue.replace(/\s+/g, " ").trim();
            if (!renameTarget || !nextTitle || savingRename) return;
            setSavingRename(true);
            setActionError(null);
            try {
              await onRename(renameTarget.id, nextTitle);
              setRenameTarget(null);
            } catch {
              setActionError("Could not rename this conversation.");
            } finally {
              setSavingRename(false);
            }
          }}
        >
          <label className="mb-1.5 block text-[length:var(--text-size-ui)] font-medium text-[var(--text-secondary)]" htmlFor="conversation-title">
            Name
          </label>
          <Input
            autoComplete="off"
            id="conversation-title"
            maxLength={120}
            name="conversation-title"
            onChange={(event) => setRenameValue(event.target.value)}
            ref={renameInputRef}
            value={renameValue}
          />
          {actionError && <p className="mt-2.5 text-[length:var(--text-size-ui)] text-[var(--status-danger-text)]" role="alert">{actionError}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <Button disabled={savingRename} onClick={() => setRenameTarget(null)} variant="ghost">
              Cancel
            </Button>
            <Button
              disabled={!renameValue.trim()}
              loading={savingRename}
              type="submit"
            >
              Save
            </Button>
          </div>
        </form>
      </Dialog>

      <Dialog
        className="max-w-sm"
        onClose={() => {
          if (!deleteTarget || !deletingIds.has(deleteTarget.id)) setDeleteTarget(null);
        }}
        open={Boolean(deleteTarget)}
        title="Hide conversation?"
      >
        <p className="text-[length:var(--text-size-nav)] text-[var(--text-secondary)]">
          This will hide “{deleteTarget?.title}”. Its locally stored messages are retained.
        </p>
        {actionError && <p className="mt-2.5 text-[length:var(--text-size-ui)] text-[var(--status-danger-text)]" role="alert">{actionError}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Button
            disabled={Boolean(deleteTarget && deletingIds.has(deleteTarget.id))}
            onClick={() => setDeleteTarget(null)}
            variant="ghost"
          >
            Cancel
          </Button>
          <Button
            loading={Boolean(deleteTarget && deletingIds.has(deleteTarget.id))}
            onClick={async () => {
              if (!deleteTarget || deletingIds.has(deleteTarget.id)) return;
              const target = deleteTarget;
              setDeletingIds((current) => new Set(current).add(target.id));
              setActionError(null);
              try {
                await onDelete(target.id);
                setDeleteTarget(null);
              } catch {
                setActionError("Could not hide this conversation.");
              } finally {
                setDeletingIds((current) => {
                  const next = new Set(current);
                  next.delete(target.id);
                  return next;
                });
              }
            }}
            variant="danger"
          >
            Hide
          </Button>
        </div>
      </Dialog>
    </div>
  );
}


function groupConversations(conversations: ChatConversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const previousSevenDays = today - 7 * 24 * 60 * 60 * 1000;
  const previousThirtyDays = today - 30 * 24 * 60 * 60 * 1000;

  return [
    {
      label: "Today",
      items: conversations.filter((conversation) => conversation.updatedAt >= today),
    },
    {
      label: "Previous 7 days",
      items: conversations.filter(
        (conversation) =>
          conversation.updatedAt < today &&
          conversation.updatedAt >= previousSevenDays
      ),
    },
    {
      label: "Previous 30 days",
      items: conversations.filter(
        (conversation) =>
        conversation.updatedAt < previousSevenDays &&
          conversation.updatedAt >= previousThirtyDays
      ),
    },
    {
      label: "Older",
      items: conversations.filter((conversation) => conversation.updatedAt < previousThirtyDays),
    },
  ];
}

function formatConversationTitle(title: string) {
  const cleaned = title.replace(/\s+/g, " ").trim();
  if (!cleaned || cleaned === "New conversation") return "New conversation";

  return cleaned
    .replace(/^(please|can you|could you|help me|tell me|show me)\s+/i, "")
    .replace(/[?.!]+$/, "");
}
