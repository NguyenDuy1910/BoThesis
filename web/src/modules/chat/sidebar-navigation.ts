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

export interface SidebarDestination {
  id: "knowledge" | "apps" | "agents" | "admin";
  label: string;
  href: string;
  icon: LucideIcon;
  /** Any one of these permissions makes this product area relevant. */
  permissionCodes: readonly string[];
}

export const sidebarNavigationItems: readonly SidebarNavigationItem[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
];

export const sidebarSecondaryDestinations: readonly SidebarDestination[] = [
  {
    id: "knowledge",
    label: "Knowledge",
    href: "/admin/collections",
    icon: LibraryBig,
    permissionCodes: ["item.manage"],
  },
  {
    id: "apps",
    label: "Apps",
    href: "/admin/connectors",
    icon: Grid2X2,
    permissionCodes: ["source.manage"],
  },
  {
    id: "agents",
    label: "Agents",
    href: "/workflows",
    icon: Bot,
    permissionCodes: ["source.manage"],
  },
  {
    id: "admin",
    label: "Admin",
    href: "/admin",
    icon: ShieldCheck,
    permissionCodes: [
      "admin",
      "item.manage",
      "source.manage",
      "user.manage",
      "role.manage",
      "group.manage",
      "access.manage",
      "audit.read",
      "tenant.manage",
    ],
  },
];
