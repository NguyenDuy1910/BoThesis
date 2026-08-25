import {
  LibraryBig,
  PlugZap,
  RefreshCw,
  ShieldCheck,
  Search,
  SquarePen,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type SidebarNavigationItemId =
  | "new-chat"
  | "search-chats";

export interface SidebarNavigationItem {
  id: SidebarNavigationItemId;
  label: string;
  icon: LucideIcon;
}

export const sidebarNavigationItems: readonly SidebarNavigationItem[] = [
  { id: "new-chat", label: "New chat", icon: SquarePen },
  { id: "search-chats", label: "Search chats", icon: Search },
];

export const sidebarSecondaryDestinations = [
  { id: "knowledge", label: "Knowledge spaces", href: "/admin/knowledge-bases", icon: LibraryBig },
  { id: "tools", label: "Plugins & tools", href: "/admin/sources", icon: PlugZap },
  { id: "workflows", label: "Workflows", href: "/workflows", icon: Workflow },
  { id: "sync", label: "Sync activity", href: "/admin/sync-activity", icon: RefreshCw },
  { id: "admin", label: "Admin console", href: "/admin/overview", icon: ShieldCheck },
] as const;
