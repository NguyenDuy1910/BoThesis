import {
  Bot,
  Grid2X2,
  LibraryBig,
  MessageSquare,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

/** The five product-level destinations shown in every product launcher. */
export interface ProductNavigationItem {
  id: "chat" | "knowledge" | "apps" | "agents" | "admin";
  label: string;
  href: string;
  icon: LucideIcon;
  /** Omit for the conversation workspace, which is always available. */
  permissionCodes?: readonly string[];
}

/**
 * One source of truth for product navigation. Shells may present these links
 * differently, but they must never change their icon, URL, or active rule.
 */
export const productNavigationItems: readonly ProductNavigationItem[] = [
  { id: "chat", label: "Chat", href: "/app", icon: MessageSquare },
  {
    id: "knowledge",
    label: "Knowledge",
    href: "/knowledge",
    icon: LibraryBig,
    permissionCodes: ["knowledge.read"],
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

/** Product routes own their entire nested path; Chat owns only its root. */
export function isProductNavigationActive(pathname: string, href: string) {
  if (href === "/app") return pathname === href;
  // Apps is nested under the Admin URL namespace, but it is a distinct
  // product destination. Do not light both product tabs at once.
  if (href === "/admin") {
    return pathname === href || (
      pathname.startsWith(`${href}/`) && !pathname.startsWith("/admin/connectors")
    );
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}
