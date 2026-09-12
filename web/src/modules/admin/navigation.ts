import {
  Boxes,
  CalendarClock,
  FileText,
  LayoutDashboard,
  type LucideIcon,
  Plug,
  ScrollText,
  Settings,
  ShieldCheck,
  Waypoints,
  Workflow,
} from "lucide-react";

import {
  hasAnySessionPermission,
  type AuthSession,
} from "@/lib/auth/session";

/**
 * One registry behind the sidebar, the breadcrumb, the page header and the
 * command palette. A section can only be reached through an entry here, so a
 * screen can never end up with a nav label and a title that disagree.
 */
export interface AdminRoute {
  /** Section key handed to the Admin router. */
  id: string;
  path: string;
  /** The single name for this concept, everywhere it appears. */
  label: string;
  description: string;
  icon: LucideIcon;
  group: AdminNavGroupId;
  /** Extra terms the command palette should match. */
  keywords?: string[];
  /** Leaves the Admin console. */
  external?: boolean;
  /** Hidden from the sidebar but still routable and searchable. */
  hidden?: boolean;
  /** Any matching permission exposes this section in the control plane. */
  permissionCodes: readonly string[];
}

export type AdminNavGroupId = "root" | "knowledge" | "operations" | "governance";

export const adminNavGroupLabels: Record<AdminNavGroupId, string | null> = {
  root: null,
  knowledge: "Knowledge",
  operations: "Operations",
  governance: "Governance",
};

export const adminRoutes: AdminRoute[] = [
  {
    id: "dashboard",
    path: "/admin",
    label: "Dashboard",
    description: "What changed in this workspace and what needs your attention.",
    icon: LayoutDashboard,
    group: "root",
    keywords: ["home", "overview", "start"],
    permissionCodes: ["admin"],
  },
  {
    id: "collections",
    path: "/admin/collections",
    label: "Collections",
    description:
      "Group trusted knowledge so teams and assistants search the right material.",
    icon: Boxes,
    group: "knowledge",
    keywords: ["knowledge base", "kb", "corpus", "library"],
    permissionCodes: ["item.manage"],
  },
  {
    id: "documents",
    path: "/admin/documents",
    label: "Documents",
    description:
      "Every file across your collections, with what is searchable and what needs a retry.",
    icon: FileText,
    group: "knowledge",
    keywords: ["files", "items", "content", "uploads"],
    permissionCodes: ["item.manage"],
  },
  {
    id: "connectors",
    path: "/admin/connectors",
    label: "Connectors",
    description:
      "Connect the systems your teams already work in and keep their content in sync.",
    icon: Plug,
    group: "knowledge",
    keywords: ["sources", "integrations", "confluence", "slack", "jira", "drive"],
    permissionCodes: ["source.manage"],
  },
  {
    id: "schedules",
    path: "/admin/schedules",
    label: "Schedules",
    description:
      "Decide how often each connected source re-imports, and pause it when you need to.",
    icon: CalendarClock,
    group: "operations",
    keywords: ["cron", "automation", "recurring", "sync schedule"],
    permissionCodes: ["source.manage"],
  },
  {
    id: "activity",
    path: "/admin/activity",
    label: "Sync activity",
    description: "Every import run, why it ran, and what it changed.",
    icon: Waypoints,
    group: "operations",
    keywords: ["runs", "ingestion", "jobs", "history", "imports"],
    permissionCodes: ["source.manage"],
  },
  {
    id: "workflows",
    path: "/workflows",
    label: "Workflows",
    description: "Automations built on top of your knowledge.",
    icon: Workflow,
    group: "operations",
    external: true,
    permissionCodes: ["source.manage"],
  },
  {
    id: "access",
    path: "/admin/access",
    label: "Access",
    description:
      "Who belongs to this workspace and what each person is allowed to reach.",
    icon: ShieldCheck,
    group: "governance",
    keywords: [
      "people",
      "users",
      "members",
      "groups",
      "teams",
      "roles",
      "permissions",
      "requests",
      "policies",
    ],
    permissionCodes: [
      "user.manage",
      "role.manage",
      "group.manage",
      "access.manage",
    ],
  },
  {
    id: "audit",
    path: "/admin/audit",
    label: "Audit log",
    description: "An append-only record of every administrative change.",
    icon: ScrollText,
    group: "governance",
    keywords: ["history", "events", "compliance", "who did what"],
    permissionCodes: ["audit.read"],
  },
  {
    id: "settings",
    path: "/admin/settings",
    label: "Settings",
    description: "Workspace identity and defaults.",
    icon: Settings,
    group: "governance",
    keywords: ["workspace", "tenant", "space", "profile", "appearance", "theme"],
    permissionCodes: ["tenant.manage"],
  },
];

export const adminNavGroups: { id: AdminNavGroupId; routes: AdminRoute[] }[] = (
  ["root", "knowledge", "operations", "governance"] as AdminNavGroupId[]
).map((id) => ({
  id,
  routes: adminRoutes.filter((route) => route.group === id && !route.hidden),
}));

export function canAccessAdminRoute(
  route: AdminRoute,
  session: AuthSession | null,
): boolean {
  return hasAnySessionPermission(session, route.permissionCodes);
}

export function visibleAdminNavGroups(session: AuthSession | null) {
  return adminNavGroups
    .map((group) => ({
      ...group,
      routes: group.routes.filter((route) => canAccessAdminRoute(route, session)),
    }))
    .filter((group) => group.routes.length > 0);
}

/** The first allowed console section is the safe Admin destination. */
export function firstAccessibleAdminRoute(session: AuthSession | null) {
  return adminRoutes.find((route) =>
    !route.external && canAccessAdminRoute(route, session),
  );
}

/**
 * Paths this console used to publish. They still resolve so existing links and
 * bookmarks keep working; the router rewrites the address bar to the current
 * path so only one name for a concept stays in circulation.
 */
export const legacySectionAliases: Record<string, string> = {
  "": "dashboard",
  overview: "dashboard",
  "knowledge-bases": "collections",
  "all-items": "documents",
  items: "documents",
  sources: "connectors",
  "sync-activity": "activity",
  "ingestion/jobs": "activity",
  "audit-logs": "audit",
  spaces: "settings",
  "workspace-settings": "settings",
  people: "access",
  users: "access",
  groups: "access?tab=groups",
  roles: "access?tab=roles",
  "access-requests": "access?tab=requests",
  "access-policies": "access",
  acl: "access",
};

export function findRoute(id: string): AdminRoute | undefined {
  return adminRoutes.find((route) => route.id === id);
}

/** Resolves any incoming Admin path segment to a canonical section. */
export function resolveSection(rawSection: string): {
  section: string;
  detailId?: string;
  canonicalPath: string;
  redirect: boolean;
} {
  const trimmed = rawSection.replace(/^\/+|\/+$/g, "");
  const [head, ...rest] = trimmed.split("/");
  const detailId = rest.join("/") || undefined;

  const alias = legacySectionAliases[head] ?? legacySectionAliases[trimmed];
  if (alias) {
    const [aliasSection, aliasQuery] = alias.split("?");
    const route = findRoute(aliasSection);
    const base = route?.path ?? "/admin";
    return {
      section: aliasSection,
      detailId,
      canonicalPath: `${base}${detailId ? `/${detailId}` : ""}${aliasQuery ? `?${aliasQuery}` : ""}`,
      redirect: true,
    };
  }

  const route = findRoute(head);
  return {
    section: route ? head : head || "dashboard",
    detailId,
    canonicalPath: `${route?.path ?? "/admin"}${detailId ? `/${detailId}` : ""}`,
    redirect: false,
  };
}
