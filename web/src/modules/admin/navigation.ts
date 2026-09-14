import type { LucideIcon } from "lucide-react";

import {
  modeForPath,
  platformAdminRailItems,
  workspaceAdminRailItems,
  workspaceAdminRailTail,
  type RailItem,
} from "@/lib/navigation";
import { hasAnySessionPermission, hasPlatformScope, type AuthSession } from "@/lib/auth/session";

/**
 * Admin addressing, derived from the rails.
 *
 * The rails in `@/lib/navigation` decide what exists and where it lives. This
 * module only adds what the command palette and the breadcrumb need on top of
 * that: a sentence per section, and the older addresses that must keep
 * resolving so an existing link never dead-ends.
 */
export type AdminNavGroupId = "workspace" | "platform";

export const adminNavGroupLabels: Record<AdminNavGroupId, string> = {
  workspace: "Workspace admin",
  platform: "Platform admin",
};

export interface AdminRoute {
  id: string;
  path: string;
  label: string;
  description: string;
  /** Older names for this section, so searching the old word still finds it. */
  keywords: string[];
  icon: LucideIcon;
  group: AdminNavGroupId;
}

/**
 * Addresses that predate the Workspace Architecture.
 *
 * Members, roles and groups became tabs of one Access section; knowledge
 * governance, connectors and apps all became Knowledge; the audit log became
 * Activity. Each old address resolves to its successor and rewrites the bar.
 */
export const legacySectionAliases: Record<string, string> = {
  "": "overview",
  dashboard: "overview",
  members: "access",
  people: "access",
  roles: "access",
  groups: "access",
  "knowledge-governance": "knowledge",
  connectors: "knowledge",
  sources: "knowledge",
  apps: "knowledge",
  "apps-permissions": "knowledge",
  "agents-policies": "agent",
  audit: "activity",
  "audit-logs": "activity",
  "workspace-settings": "settings",
  "platform/overview": "platform-tenants",
  "platform/workspaces": "platform-tenants",
  "platform/policies": "platform-models",
  "platform/health": "platform-system",
};

const DESCRIPTIONS: Record<string, string> = {
  overview: "What is configured in this workspace, and what needs attention.",
  knowledge: "The documents and sources this workspace's agent can read.",
  agent: "Identity, instructions, model, capabilities and tools.",
  access: "Who can use this workspace, and who administers it.",
  experience: "Branding, welcome copy and starter prompts.",
  activity: "What changed here, who changed it, and whether it worked.",
  settings: "Workspace identity, data region, retention and lifecycle.",
  "platform-tenants": "Every tenant on this deployment. Users see these as workspaces.",
  "platform-users": "Everyone signed in, their memberships and platform authority.",
  "platform-public-workspaces": "Tenants published to everyone, and where new users land.",
  "platform-models": "Which models and capabilities tenants are allowed to use.",
  "platform-integrations": "Connector availability, and every running connection.",
  "platform-usage": "Volume and cost across tenants.",
  "platform-audit": "The immutable record, for investigation.",
  "platform-system": "Operational health and deployment configuration.",
};

/** Platform ids are prefixed so a workspace section can never collide with one. */
function sectionId(item: RailItem, group: AdminNavGroupId) {
  return group === "platform" ? `platform-${item.id}` : item.id;
}

const keywordsById = new Map<string, string[]>();
for (const [legacy, target] of Object.entries(legacySectionAliases)) {
  if (!legacy) continue;
  keywordsById.set(target, [...(keywordsById.get(target) ?? []), legacy.replace(/[-/]/g, " ")]);
}

function toRoute(item: RailItem, group: AdminNavGroupId): AdminRoute {
  const id = sectionId(item, group);
  return {
    id,
    path: item.href,
    label: item.label,
    description: DESCRIPTIONS[id] ?? "",
    keywords: keywordsById.get(id) ?? [],
    icon: item.icon,
    group,
  };
}

export const adminRoutes: AdminRoute[] = [
  ...workspaceAdminRailItems.map((item) => toRoute(item, "workspace")),
  ...workspaceAdminRailTail.map((item) => toRoute(item, "workspace")),
  ...platformAdminRailItems.map((item) => toRoute(item, "platform")),
];

const permissionsById = new Map<string, readonly string[] | undefined>(
  [...workspaceAdminRailItems, ...workspaceAdminRailTail].map(
    (item) => [sectionId(item, "workspace"), item.permissionCodes] as const,
  ),
);

export function canAccessAdminRoute(route: AdminRoute, session: AuthSession | null): boolean {
  if (route.group === "platform") return hasPlatformScope(session, "root_admin");
  const codes = permissionsById.get(route.id);
  return !codes || hasAnySessionPermission(session, codes);
}

export function findRoute(id: string): AdminRoute | undefined {
  return adminRoutes.find((route) => route.id === id);
}

/** The route whose section a given address belongs to, nested pages included. */
export function routeForPath(pathname: string): AdminRoute | undefined {
  const platform = modeForPath(pathname) === "platform-admin";
  const candidates = adminRoutes.filter((route) => route.group === (platform ? "platform" : "workspace"));
  return (
    candidates.find((route) => route.path === pathname)
    ?? candidates
      .filter((route) => pathname.startsWith(`${route.path}/`))
      .sort((a, b) => b.path.length - a.path.length)[0]
  );
}

/** Path suffix — everything after `/admin/` — to the route that owns it. */
const byPath = new Map<string, AdminRoute>(
  adminRoutes.map((route) => [route.path.replace(/^\/admin\/?/, ""), route]),
);

export function resolveSection(rawSection: string): {
  section: string;
  canonicalPath: string;
  redirect: boolean;
} {
  const trimmed = rawSection.replace(/^\/+|\/+$/g, "");
  const alias = legacySectionAliases[trimmed];
  if (alias) {
    return { section: alias, canonicalPath: findRoute(alias)?.path ?? "/admin", redirect: true };
  }
  const route = byPath.get(trimmed);
  return {
    section: route?.id ?? (trimmed || "overview"),
    canonicalPath: route?.path ?? "/admin",
    redirect: false,
  };
}
