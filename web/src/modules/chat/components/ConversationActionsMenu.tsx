"use client";

import {
  EyeOff,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
} from "lucide-react";

import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";

interface ConversationActionsMenuProps {
  conversationTitle: string;
  deleting?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRename: () => void;
  onDelete: () => void;
}

export function ConversationActionsMenu({
  conversationTitle,
  deleting = false,
  open,
  onOpenChange,
  onRename,
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
        icon={<Pencil aria-hidden="true" size={16} />}
        label="Rename"
        onClick={onRename}
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
  onClick: () => void;
}) {
  return (
    <DropdownItem
      aria-label={label}
      className="sidebar-popover__item"
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </DropdownItem>
  );
}
