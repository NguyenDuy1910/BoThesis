import {
  Bot,
  BookOpenCheck,
  LayoutDashboard,
  type LucideIcon,
  Plug,
  ScrollText,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  UsersRound,
} from "lucide-react";

import {
  hasAnySessionPermission,
  hasPlatformScope,
  type AuthSession,
} from "@/lib/auth/session";

export interface AdminRoute {
  id: string;
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
  group: AdminNavGroupId;
  keywords?: string[];
  hidden?: boolean;
  permissionCodes: readonly string[];
  platformOnly?: boolean;
}

export type AdminNavGroupId = "workspace" | "platform";

export const adminNavGroupLabels: Record<AdminNavGroupId, string> = {
  workspace: "WORKSPACE",
  platform: "PLATFORM ADMIN",
};

export const adminRoutes: AdminRoute[] = [
  { id: "overview", path: "/admin", label: "Overview", description: "What is configured in this workspace and what needs attention.", icon: LayoutDashboard, group: "workspace", permissionCodes: ["admin"] },
  { id: "members", path: "/admin/members", label: "Members", description: "Invite workspace members and review their access.", icon: Users, group: "workspace", permissionCodes: ["user.manage"] },
  { id: "roles", path: "/admin/roles", label: "Roles & access", description: "Manage workspace roles, groups, and access requests.", icon: ShieldCheck, group: "workspace", permissionCodes: ["role.manage", "group.manage", "access.manage"] },
  { id: "knowledge-governance", path: "/admin/knowledge-governance", label: "Knowledge governance", description: "Review collection access and governed knowledge.", icon: BookOpenCheck, group: "workspace", permissionCodes: ["access.manage", "knowledge.read"] },
  // Apps has a dedicated product shell at /apps. Retain this address only as
  // a compatible deep link for bookmarks and existing admin links.
  { id: "apps-permissions", path: "/admin/apps-permissions", label: "Apps & permissions", description: "Manage connected apps and approved external actions.", icon: Plug, group: "workspace", hidden: true, permissionCodes: ["source.manage"] },
  { id: "agents-policies", path: "/admin/agents-policies", label: "Agents & policies", description: "Govern shared agents, tools, and approval policy.", icon: Bot, group: "workspace", permissionCodes: ["admin"] },
  { id: "audit", path: "/admin/audit", label: "Audit", description: "Review administrative events for this workspace.", icon: ScrollText, group: "workspace", permissionCodes: ["audit.read"] },
  { id: "settings", path: "/admin/settings", label: "Settings", description: "Manage workspace identity, defaults, and lifecycle settings.", icon: Settings, group: "workspace", permissionCodes: ["tenant.manage"] },
  { id: "platform-overview", path: "/admin/platform", label: "Platform overview", description: "Review platform-wide workspace health and open reviews.", icon: LayoutDashboard, group: "platform", permissionCodes: [], platformOnly: true },
  { id: "platform-workspaces", path: "/admin/platform/workspaces", label: "Workspaces", description: "Review workspace ownership, members, connections, and status.", icon: UsersRound, group: "platform", permissionCodes: [], platformOnly: true },
  { id: "platform-users", path: "/admin/platform/users", label: "Users", description: "Review people, memberships, workspace roles, and platform scopes.", icon: Users, group: "platform", permissionCodes: [], platformOnly: true },
  { id: "platform-policies", path: "/admin/platform/policies", label: "Global policies", description: "Review platform defaults and their workspace inheritance.", icon: SlidersHorizontal, group: "platform", permissionCodes: [], platformOnly: true },
  { id: "platform-health", path: "/admin/platform/health", label: "System health", description: "Review platform operational health.", icon: BookOpenCheck, group: "platform", permissionCodes: [], platformOnly: true },
  { id: "platform-audit", path: "/admin/platform/audit", label: "Platform audit", description: "Review administrative events across workspaces.", icon: ScrollText, group: "platform", permissionCodes: [], platformOnly: true },
];

export const adminNavGroups: { id: AdminNavGroupId; routes: AdminRoute[] }[] = (
  ["workspace", "platform"] as AdminNavGroupId[]
).map((id) => ({ id, routes: adminRoutes.filter((route) => route.group === id && !route.hidden) }));

export function canAccessAdminRoute(route: AdminRoute, session: AuthSession | null): boolean {
  return route.platformOnly
    ? hasPlatformScope(session, "root_admin")
    : hasAnySessionPermission(session, route.permissionCodes);
}

export function visibleAdminNavGroups(session: AuthSession | null) {
  return adminNavGroups
    .map((group) => ({ ...group, routes: group.routes.filter((route) => canAccessAdminRoute(route, session)) }))
    .filter((group) => group.routes.length > 0);
}

export function firstAccessibleAdminRoute(session: AuthSession | null) {
  return adminRoutes.find((route) => canAccessAdminRoute(route, session));
}

export const legacySectionAliases: Record<string, string> = {
  "": "overview",
  dashboard: "overview",
  access: "members",
  people: "members",
  groups: "roles",
  connectors: "apps-permissions",
  sources: "apps-permissions",
  "workspace-settings": "settings",
  "audit-logs": "audit",
};

export function findRoute(id: string): AdminRoute | undefined {
  return adminRoutes.find((route) => route.id === id);
}

export function resolveSection(rawSection: string): { section: string; canonicalPath: string; redirect: boolean } {
  const trimmed = rawSection.replace(/^\/+|\/+$/g, "");
  const alias = legacySectionAliases[trimmed];
  if (alias) {
    const route = findRoute(alias);
    return { section: alias, canonicalPath: route?.path ?? "/admin", redirect: true };
  }
  const route = adminRoutes.find((entry) => entry.path.replace(/^\/admin\/?/, "") === trimmed);
  return { section: route?.id ?? (trimmed || "overview"), canonicalPath: route?.path ?? "/admin", redirect: false };
}
