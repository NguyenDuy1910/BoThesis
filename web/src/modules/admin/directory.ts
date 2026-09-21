/**
 * The identity side of the Admin console: workspaces, members, groups, roles,
 * and the audit trail — read from and written to the real API.
 *
 * Types here mirror the API payloads rather than reshaping them, so a screen
 * shows what the server actually said. Where a screen needs a different word
 * for something, it maps at the point of display.
 */

import { adminRequest, queryString } from "@/modules/admin/api";
import { invalidateApiData } from "@/lib/api/revision";
import type { Paginated } from "@/modules/admin/collections";
import { getAuthSession } from "@/lib/auth/session";

export interface Workspace {
  id: string;
  code: string;
  name: string;
  status: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceHealth extends Workspace {
  owner: { display_name: string | null; email: string } | null;
  member_count: number;
  connection_count: number;
}

export interface RoleRef {
  id: string;
  code: string;
  display_name: string;
}

export interface GroupRef {
  id: string;
  code: string;
  display_name: string;
}

export interface Member {
  [key: string]: unknown;
  id: string;
  email: string;
  display_name: string | null;
  status: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  membership: {
    status: string;
    joined_at: string | null;
    roles: RoleRef[];
  };
  groups: GroupRef[];
}

export interface Group {
  [key: string]: unknown;
  id: string;
  tenant_id: string;
  code: string;
  display_name: string;
  description: string | null;
  status: string;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface Role {
  [key: string]: unknown;
  id: string;
  tenant_id: string | null;
  code: string;
  display_name: string;
  scope_type: "platform" | "tenant" | "collection";
  is_system: boolean;
  permission_codes: string[];
  status: string;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface Permission {
  code: string;
  description: string;
  scopes: string[];
}

export interface AuditEvent {
  [key: string]: unknown;
  id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  details: Record<string, unknown>;
  actor: { id: string | null; email: string | null; display_name: string | null };
  created_at: string | null;
  /** Present only on the platform trail; null for a platform-scoped action. */
  workspace?: { id: string; name: string | null } | null;
}

export interface PlatformUser {
  [key: string]: unknown;
  id: string;
  email: string;
  display_name: string | null;
  status: boolean;
  platform_roles: string[];
  memberships: { workspace_id: string; workspace_name: string; role_names: string[] }[];
}

export interface WorkspaceOverview {
  tenant: { id: string; code: string; name: string; status: string; updated_at: string | null };
  metrics: Record<string, number>;
  attention: Record<string, number>;
  recent_activity: AuditEvent[];
  generated_at: string | null;
}

export interface PlatformOverview {
  metrics: Record<string, number>;
  workspace_health: WorkspaceHealth[];
}

/** A page size that reads as "everything" for directories this size. */
const ALL = 100;

export const directoryApi = {
  workspaces: () => adminRequest<Paginated<Workspace>>("/workspaces"),
  workspace: (tenantId: string) => adminRequest<Workspace>(`/workspaces/${tenantId}`),
  async saveWorkspace(tenantId: string, patch: { name?: string; settings?: Record<string, unknown> }) {
    const saved = await adminRequest<Workspace>(`/workspaces/${tenantId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    invalidateApiData();
    return saved;
  },

  overview: (workspaceId = getAuthSession()?.active_tenant_id ?? "") => adminRequest<WorkspaceOverview>(`/workspaces/${workspaceId}/overview`),

  members: (search = "") =>
    adminRequest<Paginated<Member>>(`/users${queryString({ page_size: ALL, search })}`),
  async saveMember(
    userId: string,
    patch: { display_name?: string; role_ids?: string[]; status?: boolean; group_ids?: string[] },
  ) {
    const saved = await adminRequest<Member>(`/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    invalidateApiData();
    return saved;
  },
  async createMember(input: {
    email: string;
    display_name?: string | null;
    role_ids: string[];
    group_ids?: string[];
  }) {
    const created = await adminRequest<Member>("/users", {
      method: "POST",
      body: JSON.stringify({ group_ids: [], ...input }),
    });
    invalidateApiData();
    return created;
  },

  groups: (search = "") =>
    adminRequest<Paginated<Group>>(`/groups${queryString({ page_size: ALL, search })}`),
  async createGroup(input: { code: string; display_name: string; description?: string }) {
    const created = await adminRequest<Group>("/groups", {
      method: "POST",
      body: JSON.stringify(input),
    });
    invalidateApiData();
    return created;
  },

  roles: () => adminRequest<Paginated<Role>>(`/roles${queryString({ page_size: ALL })}`),
  permissions: () => adminRequest<{ items: Permission[]; total: number }>("/permissions"),
  async createRole(input: { code: string; display_name: string; permission_codes: string[] }) {
    const created = await adminRequest<Role>("/roles", {
      method: "POST",
      body: JSON.stringify(input),
    });
    invalidateApiData();
    return created;
  },

  auditLogs: (search = "") =>
    adminRequest<Paginated<AuditEvent>>(`/audit-logs${queryString({ page_size: ALL, search })}`),

  platform: {
    overview: () => adminRequest<PlatformOverview>("/platform/overview"),
    workspaces: (search = "") =>
      adminRequest<Paginated<WorkspaceHealth>>(
        `/platform/workspaces${queryString({ page_size: ALL, search })}`,
      ),
    users: (search = "") =>
      adminRequest<Paginated<PlatformUser>>(
        `/platform/users${queryString({ page_size: ALL, search })}`,
      ),
    audit: (search = "") =>
      adminRequest<Paginated<AuditEvent>>(
        `/platform/audit-logs${queryString({ page_size: ALL, search })}`,
      ),
    health: () => adminRequest<SystemHealth>("/platform/health"),
  },
};

export interface SystemHealth {
  status: "healthy" | "degraded" | "unhealthy";
  checked_at: string;
  duration_ms: number;
  services: {
    name: string;
    status: "healthy" | "degraded" | "unhealthy";
    required: boolean;
    latency_ms?: number | null;
    detail?: string | null;
  }[];
}

/** People are named by their display name, and by their email when they have none. */
export function memberName(member: { display_name: string | null; email: string }): string {
  return member.display_name?.trim() || member.email;
}

/** The API models a member's lifecycle as a boolean; screens show a word. */
export function memberStatus(member: Member): "active" | "suspended" {
  return member.status && member.membership.status === "active" ? "active" : "suspended";
}

export function roleNames(member: Member): string {
  return member.membership.roles.map((role) => role.display_name).join(", ");
}
