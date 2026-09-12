"use client";

import clsx from "clsx";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Laptop,
  MessageSquare,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings2,
  Sun,
  UserCircle,
  X,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { ProductMark } from "@/components/ui/ProductMark";
import { ProductSidebarGlobalNavigation } from "@/components/ui/ProductSidebarGlobalNavigation";
import { appBrand } from "@/lib/brand";
import {
  getAuthSession,
  hasSessionPermission,
  type AuthSession,
} from "@/lib/auth/session";
import { switchWorkspace } from "@/modules/auth/api";
import type { ChatConversation } from "@/modules/chat/types";
import { ConversationActionsMenu } from "./ConversationActionsMenu";
import { useTheme } from "../hooks/useTheme";

interface AppSidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  conversations: ChatConversation[];
  activeId: string | null;
  isLoading: boolean;
  onToggleCollapse: () => void;
  onCloseMobile: () => void;
  onNewChat: () => void;
  onSelectConversation: (id: string) => void;
  onRenameConversation: (id: string, title: string) => void | Promise<void>;
  onDeleteConversation: (id: string) => void | Promise<void>;
  searchRequested?: boolean;
  onSearchRequestHandled?: () => void;
}

export function AppSidebar({
  collapsed,
  mobileOpen,
  conversations,
  activeId,
  isLoading,
  onToggleCollapse,
  onCloseMobile,
  onNewChat,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  searchRequested = false,
  onSearchRequestHandled,
}: AppSidebarProps) {
  const isCollapsed = collapsed && !mobileOpen;
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  useEffect(() => {
    if (!isCollapsed) return;
    setSearchOpen(false);
    setSearchQuery("");
  }, [isCollapsed]);

  useEffect(() => {
    if (!searchRequested) return;
    setSearchOpen(true);
    onSearchRequestHandled?.();
  }, [onSearchRequestHandled, searchRequested]);

  return (
    <aside
      className={clsx(
        "sidebar",
        isCollapsed && "sidebar--collapsed",
        mobileOpen && "sidebar--mobile-open"
      )}
    >
      <SidebarHeader
        collapsed={isCollapsed}
        mobileOpen={mobileOpen}
        onCloseMobile={onCloseMobile}
        onToggleCollapse={onToggleCollapse}
      />

      <ProductSidebarGlobalNavigation
        collapsed={isCollapsed}
        onNewChat={onNewChat}
        onNavigate={onCloseMobile}
        onSearchChats={() => setSearchOpen(true)}
      />

      <SidebarChatSearch
        collapsed={isCollapsed}
        onSearchChange={setSearchQuery}
        searchOpen={searchOpen}
        searchQuery={searchQuery}
        setSearchOpen={setSearchOpen}
      />

      <RecentChatList
        collapsed={isCollapsed}
        conversations={conversations}
        activeId={activeId}
        isLoading={isLoading}
        searchQuery={searchQuery}
        onSelect={(id) => {
          onSelectConversation(id);
          onCloseMobile();
        }}
        onRename={onRenameConversation}
        onDelete={onDeleteConversation}
      />

      <SidebarFooter collapsed={isCollapsed} />
    </aside>
  );
}

function SidebarHeader({
  collapsed,
  mobileOpen,
  onCloseMobile,
  onToggleCollapse,
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onToggleCollapse: () => void;
}) {
  return (
    <div className="sidebar-header">
      {!collapsed && (
        <div className="brand">
          <ProductMark decorative size="md" />
          <span className="brand-lockup">
            <span className="brand-wordmark">{appBrand.productName}</span>
          </span>
        </div>
      )}
      {collapsed && <ProductMark decorative size="md" />}
      <button
        className="sidebar-icon-btn"
        onClick={mobileOpen ? onCloseMobile : onToggleCollapse}
        title={mobileOpen ? "Close sidebar" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={mobileOpen ? true : !collapsed}
        aria-label={mobileOpen ? "Close sidebar" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {mobileOpen ? <X aria-hidden="true" size={18} /> : collapsed ? <PanelLeftOpen aria-hidden="true" size={18} /> : <PanelLeftClose aria-hidden="true" size={18} />}
      </button>
    </div>
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
    <section aria-label="Search chats" className="sidebar-chat-context">
      <div className="sidebar-search-wrap">
        <label className="sidebar-search">
          <Search aria-hidden="true" size={14} />
          <input
            aria-label="Search conversations"
            autoFocus
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search recent chats"
            type="search"
            value={searchQuery}
          />
        </label>
        <button
          aria-label="Close conversation search"
          className="sidebar-search__close"
          onClick={() => {
            onSearchChange("");
            setSearchOpen(false);
          }}
          type="button"
        >
          <X aria-hidden="true" size={15} />
        </button>
      </div>
    </section>
  );
}

const SKELETON_WIDTHS = ["75%", "90%", "68%", "82%", "72%"];

function SkeletonRows() {
  return (
    <div className="sidebar-skeleton">
      {SKELETON_WIDTHS.map((width, i) => (
        <div
          key={i}
          className="sidebar-skeleton-row"
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

  return (
    <div className="sidebar-list">
      <div
        className="sidebar-list__scroll"
        onScroll={() => setOpenMenuId(null)}
      >
        {isLoading ? (
          collapsed ? null : <SkeletonRows />
        ) : !hasConversations ? (
          !collapsed && (
            <div className="sidebar-list__empty">
              <span className="sidebar-list__empty-icon">
                <MessageSquare aria-hidden="true" size={16} />
              </span>
              <strong>{searchQuery ? "No matching chats" : "Start a conversation"}</strong>
              <span>{searchQuery ? "Try another search term." : "Your conversations will appear here."}</span>
            </div>
          )
        ) : (
          groupedConversations.map((group) => {
            if (group.items.length === 0) return null;

            return (
              <div className="sidebar-group" key={group.label}>
                {!collapsed && (
                  <p className="sidebar-group-label">{group.label}</p>
                )}
                {group.items.map((conversation) => {
                  const displayTitle = formatConversationTitle(conversation.title);
                  const isDeleting = deletingIds.has(conversation.id);

                  return (
                    <div
                      className={clsx(
                        "sidebar-conversation-item group"
                      )}
                      data-active={conversation.id === activeId}
                      key={conversation.id}
                    >
                      <button
                        className="sidebar-conversation-btn"
                        onClick={() => {
                          setOpenMenuId(null);
                          onSelect(conversation.id);
                        }}
                        aria-current={conversation.id === activeId ? "page" : undefined}
                        aria-label={collapsed ? displayTitle : undefined}
                        title={displayTitle}
                        type="button"
                      >
                        {collapsed ? (
                          <MessageSquare aria-hidden="true" size={15} />
                        ) : (
                          <span className="sidebar-conversation-title">
                            {displayTitle}
                          </span>
                        )}
                      </button>
                      {!collapsed && (
                        <ConversationActionsMenu
                          conversationTitle={displayTitle}
                          deleting={isDeleting}
                          onDelete={() => {
                            setOpenMenuId(null);
                            setActionError(null);
                            setDeleteTarget(conversation);
                          }}
                          onOpenChange={(open) => {
                            setOpenMenuId((current) => open
                              ? conversation.id
                              : current === conversation.id ? null : current);
                          }}
                          onRename={() => {
                            setOpenMenuId(null);
                            setActionError(null);
                            setRenameTarget(conversation);
                            setRenameValue(conversation.title);
                          }}
                          open={openMenuId === conversation.id}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>

      <Dialog
        className="conversation-action-dialog"
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
          <label className="conversation-action-dialog__label" htmlFor="conversation-title">
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
          {actionError && <p className="conversation-action-dialog__error" role="alert">{actionError}</p>}
          <div className="conversation-action-dialog__actions">
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
        className="conversation-action-dialog"
        onClose={() => {
          if (!deleteTarget || !deletingIds.has(deleteTarget.id)) setDeleteTarget(null);
        }}
        open={Boolean(deleteTarget)}
        title="Hide conversation?"
      >
        <p className="conversation-action-dialog__copy">
          This will hide “{deleteTarget?.title}”. Its locally stored messages are retained.
        </p>
        {actionError && <p className="conversation-action-dialog__error" role="alert">{actionError}</p>}
        <div className="conversation-action-dialog__actions">
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

function SidebarFooter({ collapsed }: { collapsed: boolean }) {
  const { theme, resolvedTheme, toggleTheme } = useTheme();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [isSwitchingWorkspace, setIsSwitchingWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  useEffect(() => setSession(getAuthSession()), []);

  const changeWorkspace = async (tenantId: string) => {
    if (tenantId === session?.active_tenant_id) return;
    setIsSwitchingWorkspace(true);
    setWorkspaceError(null);
    try {
      const next = await switchWorkspace(tenantId);
      setSession(next);
      window.location.reload();
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : "Could not change workspace.");
    } finally {
      setIsSwitchingWorkspace(false);
    }
  };

  return (
    <div className="sidebar-footer">
      {hasSessionPermission(session, "tenant.manage") && (
        <Link
          aria-label={collapsed ? "Workspace settings" : undefined}
          className="sidebar-account-row sidebar-account-row--link"
          href="/admin/settings"
          title={collapsed ? "Workspace settings" : undefined}
        >
          <Settings2 aria-hidden="true" size={17} />
          {!collapsed && <span>Workspace settings</span>}
        </Link>
      )}
      <div
        aria-label={collapsed ? "Knowledge workspace" : undefined}
        className="sidebar-account-row"
        title={collapsed ? "Knowledge workspace" : undefined}
      >
        <span className="sidebar-account-row__avatar"><UserCircle aria-hidden="true" size={18} /></span>
        {!collapsed && (
          <span className="sidebar-account-row__copy">
            <strong>{session?.display_name ?? "Workspace access"}</strong>
            {session && session.tenants.length > 1 ? (
              <select
                aria-label="Active workspace"
                className="sidebar-workspace-select"
                disabled={isSwitchingWorkspace}
                onChange={(event) => void changeWorkspace(event.target.value)}
                value={session.active_tenant_id}
              >
                {session.tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
              </select>
            ) : <small>{session?.tenants[0]?.name ?? "Private to your access"}</small>}
            {workspaceError ? <small className="sidebar-workspace-error" role="alert">{workspaceError}</small> : null}
          </span>
        )}
        <button
          aria-label={`Switch theme (currently ${theme})`}
          className="sidebar-icon-btn"
          onClick={toggleTheme}
          style={{ marginLeft: "auto" }}
          title={`Theme: ${theme} (${resolvedTheme})`}
          type="button"
        >
          {theme === "system" ? (
            <Laptop aria-hidden="true" size={16} />
          ) : resolvedTheme === "dark" ? (
            <Moon aria-hidden="true" size={16} />
          ) : (
            <Sun aria-hidden="true" size={16} />
          )}
        </button>
      </div>
    </div>
  );
}

function groupConversations(conversations: ChatConversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const recent = today - 24 * 60 * 60 * 1000;
  const previousSevenDays = today - 7 * 24 * 60 * 60 * 1000;
  const previousThirtyDays = today - 30 * 24 * 60 * 60 * 1000;

  return [
    {
      label: "Recent",
      items: conversations.filter((conversation) => conversation.updatedAt >= recent),
    },
    {
      label: "Previous 7 days",
      items: conversations.filter(
        (conversation) =>
        conversation.updatedAt < recent &&
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
