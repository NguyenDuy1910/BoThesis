import {
  Bot,
  Grid2X2,
  LibraryBig,
  MessageSquare,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

export type SidebarNavigationItemId = "chat";

export interface SidebarNavigationItem {
  id: SidebarNavigationItemId;
  label: string;
  icon: LucideIcon;
}

export const sidebarNavigationItems: readonly SidebarNavigationItem[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
];

export const sidebarSecondaryDestinations = [
  { id: "knowledge", label: "Knowledge", href: "/admin/collections", icon: LibraryBig },
  { id: "apps", label: "Apps", href: "/admin/connectors", icon: Grid2X2 },
  { id: "agents", label: "Agents", href: "/workflows", icon: Bot },
  { id: "admin", label: "Admin", href: "/admin", icon: ShieldCheck },
] as const;
