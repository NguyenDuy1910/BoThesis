"use client";

import {
  Archive,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  Pin,
  Share2,
  EyeOff,
} from "lucide-react";

import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";

interface ConversationActionsMenuProps {
  conversationTitle: string;
  deleting?: boolean;
  open: boolean;
  pinned?: boolean;
  onOpenChange: (open: boolean) => void;
  onShare?: () => void;
  onRename: () => void;
  onPin?: () => void;
  onArchive?: () => void;
  onDelete: () => void;
}

export function ConversationActionsMenu({
  conversationTitle,
  deleting = false,
  open,
  pinned = false,
  onOpenChange,
  onShare,
  onRename,
  onPin,
  onArchive,
  onDelete,
}: ConversationActionsMenuProps) {
  return (
    <Dropdown
      align="left"
      ariaLabel={`Actions for ${conversationTitle}`}
      buttonClassName="sidebar-conversation-menu__trigger"
      className="sidebar-conversation-menu"
      closeOnScroll
      label={deleting
        ? <LoaderCircle aria-hidden="true" className="spin" size={15} />
        : <MoreHorizontal aria-hidden="true" size={16} />}
      menuClassName="sidebar-popover sidebar-popover--conversation"
      onOpenChange={onOpenChange}
      open={open}
      showChevron={false}
    >
      <ConversationMenuItem
        icon={<Share2 aria-hidden="true" size={16} />}
        label="Share"
        onClick={onShare}
      />
      <ConversationMenuItem
        icon={<Pencil aria-hidden="true" size={16} />}
        label="Rename"
        onClick={onRename}
      />
      <ConversationMenuItem
        icon={<Pin aria-hidden="true" size={16} />}
        label={pinned ? "Unpin chat" : "Pin chat"}
        onClick={onPin}
      />
      <ConversationMenuItem
        icon={<Archive aria-hidden="true" size={16} />}
        label="Archive"
        onClick={onArchive}
      />
      <DropdownItem
        aria-label="Hide conversation"
        className="sidebar-popover__item sidebar-popover__item--delete"
        destructive
        disabled={deleting}
        onClick={onDelete}
      >
        <EyeOff aria-hidden="true" size={16} />
        <span>Hide conversation</span>
      </DropdownItem>
    </Dropdown>
  );
}

function ConversationMenuItem({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
}) {
  const available = Boolean(onClick);
  return (
    <DropdownItem
      aria-label={available ? label : `${label} (not available)`}
      className="sidebar-popover__item"
      disabled={!available}
      onClick={onClick}
      title={available ? undefined : "Not available yet"}
    >
      {icon}
      <span>{label}</span>
    </DropdownItem>
  );
}
