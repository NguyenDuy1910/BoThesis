import {
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
  { id: "workflows", label: "Workflows", href: "/workflows", icon: Workflow },
  { id: "admin", label: "Admin console", href: "/admin/overview", icon: ShieldCheck },
] as const;
