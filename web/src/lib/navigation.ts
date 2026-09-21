import {
  Activity,
  BookOpen,
  Bot,
  Building2,
  ChartColumn,
  Contrast,
  LayoutGrid,
  Plug,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

/**
 * The three product modes.
 *
 * They never share a rail. The rail a person is looking at is how they know
 * which mode they are in, so every mode owns its own item list and its own
 * header treatment. Moving between modes is always an explicit control.
 */
export type ProductMode = "workspace" | "workspace-control" | "platform-control";

export interface RailItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /**
   * `action` starts something in the place you already are; `destination` is
   * somewhere you go. Only a destination can be the current item, so a rail
   * never appears to have two selections.
   */
  kind: "action" | "destination";
  permissionCodes?: readonly string[];
}

/**
 * Mode 1 — User Workspace.
 *
 * Deliberately light. Workspace settings, roles, connectors and system
 * configuration are absent, not disabled: an ordinary user never sees them,
 * and a workspace operator reaches them from the workspace switcher instead.
 */
export const workspaceRailItems: readonly RailItem[] = [
  { id: "new-chat", label: "New chat", href: "/app?action=new", icon: Plus, kind: "action" },
  { id: "search", label: "Search", href: "/app?action=search", icon: Search, kind: "action" },
  { id: "library", label: "Library", href: "/library", icon: BookOpen, kind: "destination" },
];

/** Mode 2 — Workspace control for selected workspace. */
export const workspaceControlRailItems: readonly RailItem[] = [
  { id: "overview", label: "Overview", href: "/workspace-control", icon: LayoutGrid, kind: "destination", permissionCodes: ["tenant.read"] },
  { id: "knowledge", label: "Knowledge", href: "/workspace-control/knowledge", icon: BookOpen, kind: "destination", permissionCodes: ["knowledge.read"] },
  { id: "agent", label: "Agent", href: "/workspace-control/agent", icon: Bot, kind: "destination", permissionCodes: ["tenant.manage"] },
  { id: "access", label: "Access", href: "/workspace-control/access", icon: ShieldCheck, kind: "destination", permissionCodes: ["user.manage", "role.manage", "group.manage", "access.manage"] },
  { id: "experience", label: "Experience", href: "/workspace-control/experience", icon: Contrast, kind: "destination", permissionCodes: ["tenant.manage"] },
  { id: "activity", label: "Activity", href: "/workspace-control/activity", icon: Activity, kind: "destination", permissionCodes: ["audit.read"] },
];

/** Settings sits below the spacer, separated from the six sections above it. */
export const workspaceControlRailTail: readonly RailItem[] = [
  { id: "settings", label: "Settings", href: "/workspace-control/settings", icon: Settings, kind: "destination", permissionCodes: ["tenant.manage"] },
];

/**
 * Mode 3 — Platform control. Separate control plane for platform operators.
 *
 * This is the only surface in the product that speaks in tenants; everywhere a
 * normal user can reach, the same object is a workspace.
 */
export const platformControlRailItems: readonly RailItem[] = [
  { id: "tenants", label: "Tenants", href: "/workspace-control/platform", icon: Building2, kind: "destination" },
  { id: "users", label: "Users", href: "/workspace-control/platform/users", icon: Users, kind: "destination" },
  { id: "public-workspaces", label: "Public Workspaces", href: "/workspace-control/platform/public-workspaces", icon: LayoutGrid, kind: "destination" },
  { id: "models", label: "Models & Capabilities", href: "/workspace-control/platform/models", icon: Bot, kind: "destination" },
  { id: "integrations", label: "Integrations", href: "/workspace-control/platform/integrations", icon: Plug, kind: "destination" },
  { id: "usage", label: "Usage", href: "/workspace-control/platform/usage", icon: ChartColumn, kind: "destination" },
  { id: "audit", label: "Audit", href: "/workspace-control/platform/audit", icon: Activity, kind: "destination" },
  { id: "system", label: "System", href: "/workspace-control/platform/system", icon: Settings, kind: "destination" },
];

/** Which mode an address belongs to. Nothing inside a page widens scope. */
export function modeForPath(pathname: string): ProductMode {
  if (pathname === "/workspace-control/platform" || pathname.startsWith("/workspace-control/platform/")) return "platform-control";
  if (pathname === "/workspace-control" || pathname.startsWith("/workspace-control/")) return "workspace-control";
  return "workspace";
}

/**
 * Whether a rail item is the current place.
 *
 * Exact landings (`/workspace-control`, `/workspace-control/platform`) must not match their own
 * children, or two rows would light up at once. Every other destination owns
 * its nested detail addresses.
 */
export function isRailItemActive(item: RailItem, pathname: string): boolean {
  if (item.kind === "action") return false;
  const [path] = item.href.split("?");
  if (path === "/workspace-control" || path === "/workspace-control/platform") return pathname === path;
  return pathname === path || pathname.startsWith(`${path}/`);
}

/**
 * Whether the holder of a session has any one of a set of permissions.
 *
 * Passed in rather than imported so this contract stays a pure description of
 * the navigation — it has no opinion on how a session is stored or read, and
 * can be exercised without one.
 */
export type PermissionCheck = (codes: readonly string[]) => boolean;

/** The items of one mode that the caller is actually authorised to open. */
export function visibleRailItems(items: readonly RailItem[], can: PermissionCheck): RailItem[] {
  return items.filter((item) => !item.permissionCodes || can(item.permissionCodes));
}
