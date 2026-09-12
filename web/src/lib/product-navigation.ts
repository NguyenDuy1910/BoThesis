import {
  Bot,
  BookOpen,
  FileText,
  Grid2X2,
  Plus,
  Search,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

/** Product-wide actions always take a person back to Chat with explicit intent. */
export interface ProductNavigationAction {
  id: "new-chat" | "search-chats";
  label: string;
  href: string;
  icon: LucideIcon;
}

/** Product destinations shared by every module shell. */
export interface ProductNavigationItem {
  id: "knowledge" | "library" | "apps" | "agents" | "workspace";
  label: string;
  href: string;
  icon: LucideIcon;
  /** Omit for the conversation workspace, which is always available. */
  permissionCodes?: readonly string[];
}

export const productNavigationActions: readonly ProductNavigationAction[] = [
  { id: "new-chat", label: "New chat", href: "/app?action=new", icon: Plus },
  { id: "search-chats", label: "Search chats", href: "/app?action=search", icon: Search },
];

/**
 * One source of truth for product navigation. Shells may present these links
 * differently, but they must never change their icon, URL, or active rule.
 */
export const productNavigationItems: readonly ProductNavigationItem[] = [
  {
    id: "knowledge",
    label: "Knowledge",
    href: "/knowledge",
    icon: BookOpen,
    permissionCodes: ["knowledge.read"],
  },
  {
    id: "library",
    label: "Library",
    href: "/knowledge?view=library",
    icon: FileText,
    permissionCodes: ["knowledge.read"],
  },
  {
    id: "apps",
    label: "Apps",
    href: "/apps",
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
    id: "workspace",
    label: "Workspace",
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
export function isProductNavigationActive(pathname: string, href: string, search = "") {
  const [destinationPath, destinationQuery] = href.split("?");
  const query = new URLSearchParams(destinationQuery);
  const currentQuery = new URLSearchParams(search);
  if (destinationPath === "/app") return pathname === destinationPath;
  if (destinationPath === "/knowledge" && query.get("view") === "library") {
    return pathname === "/knowledge" && currentQuery.get("view") === "library";
  }
  if (destinationPath === "/knowledge") {
    return (pathname === destinationPath || pathname.startsWith(`${destinationPath}/`))
      && (pathname !== destinationPath || currentQuery.get("view") !== "library");
  }
  // Workspace owns only its own admin namespace, never another product
  // destination such as Apps or Agents.
  if (destinationPath === "/admin") {
    return pathname === destinationPath || (
      pathname.startsWith(`${destinationPath}/`) &&
      !pathname.startsWith("/admin/connectors") &&
      !pathname.startsWith("/admin/apps-permissions") &&
      !pathname.startsWith("/admin/agents-policies")
    );
  }
  return pathname === destinationPath || pathname.startsWith(`${destinationPath}/`);
}
