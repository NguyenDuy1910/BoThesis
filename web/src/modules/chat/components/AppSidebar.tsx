"use client";

import clsx from "clsx";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronRight,
  LoaderCircle,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Trash2,
  UserCircle,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { appBrand } from "@/lib/brand";
import {
  sidebarNavigationItems,
  sidebarSecondaryDestinations,
  type SidebarNavigationItem,
} from "@/modules/chat/sidebar-navigation";
import type { ChatConversation } from "@/modules/chat/types";

export function BothesisMark({
  className,
  decorative = false,
  label = appBrand.logo.alt,
}: {
  className?: string;
  decorative?: boolean;
  label?: string;
}) {
  return (
    <span
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label}
      className={clsx("bothesis-mark", className)}
      role={decorative ? undefined : "img"}
    >
      <svg
        viewBox="0 0 28 28"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        focusable="false"
        style={{ width: "100%", height: "100%", display: "block" }}
      >
        <rect width="28" height="28" rx="6" fill="#0B3A5B" />
        <rect x="8" y="6.5" width="2.5" height="15" rx="1.25" fill="white" />
        <rect x="9" y="6.5" width="9" height="2.5" rx="1.25" fill="white" />
        <rect x="9" y="12.75" width="8" height="2.5" rx="1.25" fill="white" />
        <rect x="9" y="19" width="9" height="2.5" rx="1.25" fill="white" />
        <path d="M16.5 7.75C21 8 21 13.25 16.5 14M16.5 14C21 14.75 21 20 16.5 20.25" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    </span>
  );
}

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
  onDeleteConversation: (id: string) => void | Promise<void>;
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
  onDeleteConversation,
}: AppSidebarProps) {
  const isCollapsed = collapsed && !mobileOpen;
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!searchOpen || isCollapsed) return;
    searchInputRef.current?.focus();
  }, [isCollapsed, searchOpen]);

  const activateNavigationItem = (item: SidebarNavigationItem) => {
    if (item.disabled) return;
    if (item.id === "new-chat") {
      setQuery("");
      setSearchOpen(false);
      onNewChat();
      return;
    }
    if (item.id === "search-chats") {
      if (isCollapsed) onToggleCollapse();
      setSearchOpen(true);
      searchInputRef.current?.focus();
    }
  };

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

      <SidebarNavigation
        activeConversationId={activeId}
        collapsed={isCollapsed}
        onActivate={activateNavigationItem}
        onCloseMobile={onCloseMobile}
        searchOpen={searchOpen}
      />

      {!isCollapsed && searchOpen && (
        <SidebarSearch
          inputRef={searchInputRef}
          onClose={() => {
            setQuery("");
            setSearchOpen(false);
          }}
          onQuery={setQuery}
          query={query}
        />
      )}

      <RecentChatList
        query={query}
        collapsed={isCollapsed}
        conversations={conversations}
        activeId={activeId}
        isLoading={isLoading}
        onSelect={(id) => {
          onSelectConversation(id);
          onCloseMobile();
        }}
        onDelete={(id) => {
          onDeleteConversation(id);
        }}
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
          <BothesisMark className="bothesis-mark--sidebar" decorative />
          <span className="brand-lockup">
            <span className="brand-wordmark">{appBrand.shortName}</span>
          </span>
        </div>
      )}
      {collapsed && <BothesisMark className="bothesis-mark--sidebar" decorative />}
      <button
        className="sidebar-icon-btn"
        onClick={mobileOpen ? onCloseMobile : onToggleCollapse}
        title={mobileOpen ? "Close sidebar" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={mobileOpen ? true : !collapsed}
        aria-label={mobileOpen ? "Close sidebar" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {mobileOpen ? <X size={18} /> : collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
      </button>
    </div>
  );
}

function SidebarNavigation({
  activeConversationId,
  collapsed,
  onActivate,
  onCloseMobile,
  searchOpen,
}: {
  activeConversationId: string | null;
  collapsed: boolean;
  onActivate: (item: SidebarNavigationItem) => void;
  onCloseMobile: () => void;
  searchOpen: boolean;
}) {
  const router = useRouter();

  return (
    <nav aria-label="Workspace" className="sidebar-navigation">
      {sidebarNavigationItems.map((item) => {
        if (item.id === "more") {
          return (
            <Dropdown
              align="left"
              ariaLabel="More destinations"
              buttonClassName="sidebar-row sidebar-row--menu"
              className="sidebar-more-dropdown"
              key={item.id}
              label={
                <SidebarRowContent
                  collapsed={collapsed}
                  item={item}
                />
              }
              menuClassName="sidebar-popover"
              showChevron={false}
              title={collapsed ? "More" : undefined}
            >
              {sidebarSecondaryDestinations.map((destination) => (
                <DropdownItem
                  className="sidebar-popover__item"
                  key={destination.id}
                  onClick={() => {
                    router.push(destination.href);
                    onCloseMobile();
                  }}
                >
                  <span>{destination.label}</span>
                  <ChevronRight aria-hidden="true" size={14} />
                </DropdownItem>
              ))}
            </Dropdown>
          );
        }

        const active = item.id === "search-chats"
          ? searchOpen
          : item.id === "new-chat" && activeConversationId === null;

        return (
          <SidebarRow
            active={active}
            collapsed={collapsed}
            item={item}
            key={item.id}
            onClick={() => onActivate(item)}
          />
        );
      })}
    </nav>
  );
}

function SidebarRow({
  active = false,
  collapsed,
  item,
  onClick,
}: {
  active?: boolean;
  collapsed: boolean;
  item: SidebarNavigationItem;
  onClick: () => void;
}) {
  const tooltip = item.statusLabel ? `${item.label} — ${item.statusLabel}` : item.label;

  return (
    <button
      aria-current={active ? "page" : undefined}
      aria-disabled={item.disabled || undefined}
      aria-label={collapsed ? tooltip : undefined}
      className="sidebar-row"
      data-active={active}
      data-disabled={item.disabled || undefined}
      onClick={onClick}
      title={collapsed ? tooltip : undefined}
      type="button"
    >
      <SidebarRowContent collapsed={collapsed} item={item} />
    </button>
  );
}

function SidebarRowContent({
  collapsed,
  item,
}: {
  collapsed: boolean;
  item: SidebarNavigationItem;
}) {
  const Icon = item.icon;

  return (
    <>
      <Icon aria-hidden="true" className="sidebar-row__icon" size={18} />
      {!collapsed && (
        <>
          <span className="sidebar-row__label">{item.label}</span>
          {item.statusLabel && (
            <span className="sidebar-row__status">{item.statusLabel}</span>
          )}
        </>
      )}
    </>
  );
}

function SidebarSearch({
  inputRef,
  query,
  onClose,
  onQuery,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  onClose: () => void;
  onQuery: (q: string) => void;
}) {
  return (
    <div className="sidebar-search-wrap" role="search">
      <label className="sidebar-search" htmlFor="conversation-search">
        <Search aria-hidden="true" size={16} />
        <input
          id="conversation-search"
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onClose();
          }}
          placeholder="Search chats"
          ref={inputRef}
          value={query}
        />
      </label>
      <button
        aria-label="Close conversation search"
        className="sidebar-search__close"
        onClick={onClose}
        type="button"
      >
        <X aria-hidden="true" size={15} />
      </button>
    </div>
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
  query,
  collapsed,
  conversations,
  activeId,
  isLoading,
  onSelect,
  onDelete,
}: {
  query: string;
  collapsed: boolean;
  conversations: ChatConversation[];
  activeId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void | Promise<void>;
}) {
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const groupedConversations = useMemo(
    () => groupConversations(conversations, query),
    [conversations, query]
  );
  const hasConversations = conversations.length > 0;
  const hasResults = groupedConversations.some((group) => group.items.length > 0);

  return (
    <div className="sidebar-list">
      <div className="sidebar-list__scroll">
        {isLoading ? (
          collapsed ? null : <SkeletonRows />
        ) : !hasConversations ? (
          !collapsed && (
            <div className="sidebar-list__empty">
              <span className="sidebar-list__empty-icon">
                <MessageSquare size={16} />
              </span>
              <strong>Start your first brief</strong>
              <span>Your conversations will appear here.</span>
            </div>
          )
        ) : !hasResults ? (
          !collapsed && (
            <div className="sidebar-list__empty">
              <span className="sidebar-list__empty-icon">
                <Search size={16} />
              </span>
              <strong>No matching conversations</strong>
              <span>Try a shorter search term.</span>
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
                        onClick={() => onSelect(conversation.id)}
                        aria-current={conversation.id === activeId ? "page" : undefined}
                        aria-label={collapsed ? displayTitle : undefined}
                        title={displayTitle}
                        type="button"
                      >
                        {collapsed ? (
                          <MessageSquare size={15} />
                        ) : (
                          <span className="sidebar-conversation-title">
                            {displayTitle}
                          </span>
                        )}
                      </button>
                      {!collapsed && (
                        <Dropdown
                          ariaLabel={`Actions for ${displayTitle}`}
                          buttonClassName="sidebar-conversation-menu__trigger"
                          className="sidebar-conversation-menu"
                          label={isDeleting
                            ? <LoaderCircle aria-hidden="true" className="spin" size={14} />
                            : <MoreHorizontal aria-hidden="true" size={15} />}
                          menuClassName="sidebar-popover sidebar-popover--conversation"
                          showChevron={false}
                        >
                          <DropdownItem
                            className="sidebar-popover__item"
                            destructive
                            disabled={isDeleting}
                            onClick={async () => {
                              if (isDeleting) return;
                              setDeletingIds((current) => new Set(current).add(conversation.id));
                              try {
                                await onDelete(conversation.id);
                              } finally {
                                setDeletingIds((current) => {
                                  const next = new Set(current);
                                  next.delete(conversation.id);
                                  return next;
                                });
                              }
                            }}
                          >
                            <Trash2 aria-hidden="true" size={14} />
                            <span>Delete</span>
                          </DropdownItem>
                        </Dropdown>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function SidebarFooter({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="sidebar-footer">
      <div
        aria-label={collapsed ? "Knowledge workspace" : undefined}
        className="sidebar-account-row"
        title={collapsed ? "Knowledge workspace" : undefined}
      >
        <UserCircle aria-hidden="true" size={18} />
        {!collapsed && <span>Knowledge workspace</span>}
      </div>
    </div>
  );
}

function groupConversations(conversations: ChatConversation[], query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = normalizedQuery
    ? conversations.filter((conversation) =>
        conversation.title.toLowerCase().includes(normalizedQuery)
      )
    : conversations;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const recent = today - 24 * 60 * 60 * 1000;
  const previousSevenDays = today - 7 * 24 * 60 * 60 * 1000;
  const previousThirtyDays = today - 30 * 24 * 60 * 60 * 1000;

  return [
    {
      label: "Recent",
      items: filtered.filter((conversation) => conversation.updatedAt >= recent),
    },
    {
      label: "Previous 7 days",
      items: filtered.filter(
        (conversation) =>
          conversation.updatedAt < recent &&
          conversation.updatedAt >= previousSevenDays
      ),
    },
    {
      label: "Previous 30 days",
      items: filtered.filter(
        (conversation) =>
          conversation.updatedAt < previousSevenDays &&
          conversation.updatedAt >= previousThirtyDays
      ),
    },
    {
      label: "Older",
      items: filtered.filter((conversation) => conversation.updatedAt < previousThirtyDays),
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
