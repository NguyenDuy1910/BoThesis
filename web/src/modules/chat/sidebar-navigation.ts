import {
  Blocks,
  FolderKanban,
  MoreHorizontal,
  Search,
  SquarePen,
  type LucideIcon,
} from "lucide-react";

export type SidebarNavigationItemId =
  | "new-chat"
  | "search-chats"
  | "projects"
  | "plugins"
  | "more";

export interface SidebarNavigationItem {
  id: SidebarNavigationItemId;
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
  statusLabel?: string;
}

export const sidebarNavigationItems: readonly SidebarNavigationItem[] = [
  { id: "new-chat", label: "New chat", icon: SquarePen },
  { id: "search-chats", label: "Search chats", icon: Search },
  {
    id: "projects",
    label: "Projects",
    icon: FolderKanban,
    disabled: true,
    statusLabel: "Coming soon",
  },
  {
    id: "plugins",
    label: "Plugins",
    icon: Blocks,
    disabled: true,
    statusLabel: "Coming soon",
  },
  { id: "more", label: "More", icon: MoreHorizontal },
];

export const sidebarSecondaryDestinations = [
  { id: "workflows", label: "Workflows", href: "/workflows" },
  { id: "admin", label: "Admin console", href: "/admin/overview" },
] as const;
