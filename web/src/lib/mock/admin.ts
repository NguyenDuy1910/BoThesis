type Row = Record<string, any>;

const now = "2026-08-25T08:30:00.000Z";
const earlier = "2026-08-24T03:15:00.000Z";

const connections: Row[] = [
  {
    id: "conn-confluence-product",
    plugin_key: "confluence",
    display_name: "Company Confluence",
    config: { wiki_base: "https://northstar.atlassian.net/wiki", space: "ENG", scopes: ["ENG", "PRODUCT", "SEC"] },
    credential_configured: true,
    owner_type: "tenant",
    status: "active",
    binding_count: 2,
    created_at: "2026-05-02T02:10:00.000Z",
    updated_at: now,
  },
  {
    id: "conn-files-governed",
    plugin_key: "file",
    display_name: "Governed uploads",
    config: {},
    credential_configured: true,
    owner_type: "tenant",
    status: "active",
    binding_count: 1,
    created_at: "2026-06-12T09:00:00.000Z",
    updated_at: earlier,
  },
  {
    id: "conn-confluence-legacy",
    plugin_key: "confluence",
    display_name: "Legacy Operations Wiki",
    config: { wiki_base: "https://northstar.atlassian.net/wiki", space: "OPS" },
    credential_configured: true,
    owner_type: "tenant",
    status: "error",
    binding_count: 1,
    created_at: "2026-04-18T07:00:00.000Z",
    updated_at: earlier,
  },
];

const collections: Row[] = [
  collection("kb-product", "Product & Engineering", "Product strategy, architecture decisions, and delivery standards.", "ready", true),
  collection("kb-security", "Security & Compliance", "Policies, controls, audit evidence, and incident procedures.", "ready", false),
  collection("kb-operations", "Customer Operations", "Service playbooks, escalation paths, and quality standards.", "processing", true),
  collection("kb-finance", "Finance Planning", "Planning assumptions and governed quarterly reporting.", "failed", false),
];

const documents: Row[] = [
  document("doc-product-strategy", "FY27 Product Strategy", "kb-product", "pdf", 2_480_000, "ready", true, "conn-confluence-product", "Company Confluence"),
  document("doc-architecture", "Platform Architecture Principles", "kb-product", "page", 184_000, "ready", true, "conn-confluence-product", "Company Confluence"),
  document("doc-release", "Release Readiness Checklist", "kb-product", "page", 92_000, "ready", true, "conn-confluence-product", "Company Confluence"),
  document("doc-access-policy", "Enterprise Access Control Policy", "kb-security", "pdf", 1_320_000, "ready", true, "conn-files-governed", "Governed uploads"),
  document("doc-incident", "Incident Response Handbook", "kb-security", "pdf", 3_120_000, "ready", true, "conn-files-governed", "Governed uploads"),
  document("doc-escalation", "Customer Escalation Playbook", "kb-operations", "page", 210_000, "processing", false, "conn-confluence-legacy", "Legacy Operations Wiki"),
  document("doc-q4-plan", "Q4 Operating Plan", "kb-finance", "spreadsheet", 860_000, "failed", false, "conn-files-governed", "Governed uploads"),
];

const schedules = {
  daily: { schedule_type: "cron", cron_expression: "0 2 * * *", timezone: "Asia/Ho_Chi_Minh", enabled: true, overlap_policy: "skip", next_run_at: "2026-08-26T02:00:00.000Z", last_run_at: earlier },
  weekly: { schedule_type: "cron", cron_expression: "0 2 * * 1", timezone: "Asia/Ho_Chi_Minh", enabled: true, overlap_policy: "skip", next_run_at: "2026-08-31T02:00:00.000Z", last_run_at: "2026-08-24T02:00:00.000Z" },
};

const bindings: Row[] = [
  binding("binding-product", "conn-confluence-product", "kb-product", "Product spaces", "active", schedules.daily),
  binding("binding-security", "conn-files-governed", "kb-security", "Policy library", "active", schedules.weekly),
  binding("binding-operations", "conn-confluence-legacy", "kb-operations", "Operations space", "error", schedules.daily),
  binding("binding-finance", "conn-files-governed", "kb-finance", "Finance uploads", "active", null),
];

const runs: Row[] = [
  run("run-product-complete", bindings[0], connections[0], "completed", 48, 48, 312, null, earlier),
  run("run-security-complete", bindings[1], connections[1], "completed", 17, 17, 126, null, "2026-08-24T02:00:00.000Z"),
  run("run-operations-running", bindings[2], connections[2], "running", 31, 18, 94, null, now),
  run("run-finance-failed", bindings[3], connections[1], "failed", 12, 7, 0, "Spreadsheet schema validation failed on the Forecast tab.", earlier),
  run("run-product-scheduled", bindings[0], connections[0], "pending", 0, 0, 0, null, "2026-08-26T02:00:00.000Z"),
];

const roles: Row[] = [
  { id: "role-admin", code: "workspace_admin", display_name: "Workspace admin", permission_codes: ["knowledge.read", "knowledge.manage", "source.manage", "access.manage", "audit.read"], member_count: 2, status: "active", updated_at: now },
  { id: "role-analyst", code: "knowledge_analyst", display_name: "Knowledge analyst", permission_codes: ["knowledge.read", "knowledge.query"], member_count: 12, status: "active", updated_at: earlier },
  { id: "role-viewer", code: "viewer", display_name: "Viewer", permission_codes: ["knowledge.read"], member_count: 34, status: "active", updated_at: earlier },
];

const groups: Row[] = [
  { id: "group-product", code: "product-engineering", display_name: "Product & Engineering", description: "Product and engineering organization", principal_token: "group:product-engineering", permission_codes: ["knowledge.query"], member_count: 21, status: "active", updated_at: now },
  { id: "group-security", code: "security-reviewers", display_name: "Security reviewers", description: "Security and compliance reviewers", principal_token: "group:security-reviewers", permission_codes: ["knowledge.query", "audit.read"], member_count: 6, status: "active", updated_at: earlier },
  { id: "group-contractors", code: "contractors", display_name: "Contractors", description: "Time-bound external collaborators", principal_token: "group:contractors", permission_codes: [], member_count: 4, status: "inactive", updated_at: earlier },
];

const users: Row[] = [
  user("user-maya-chen", "maya.chen@northstar.example", "Maya Chen", roles[0], [groups[0], groups[1]], "active", now),
  user("user-liam-tran", "liam.tran@northstar.example", "Liam Tran", roles[1], [groups[0]], "active", earlier),
  user("user-amara-okafor", "amara.okafor@northstar.example", "Amara Okafor", roles[1], [groups[1]], "active", "2026-08-22T04:30:00.000Z"),
  user("user-noah-williams", "noah.williams@northstar.example", "Noah Williams", roles[2], [], "inactive", "2026-07-30T01:00:00.000Z"),
];

const grants: Row[] = [
  { item_id: "kb-product", principal_type: "group", principal_id: "group-product", role: "viewer", created_at: earlier, updated_at: earlier },
  { item_id: "kb-product", principal_type: "user", principal_id: "user-maya-chen", role: "owner", created_at: earlier, updated_at: earlier },
  { item_id: "kb-security", principal_type: "group", principal_id: "group-security", role: "viewer", created_at: earlier, updated_at: earlier },
  { item_id: "kb-security", principal_type: "user", principal_id: "user-maya-chen", role: "owner", created_at: earlier, updated_at: earlier },
  { item_id: "kb-finance", principal_type: "user", principal_id: "user-maya-chen", role: "owner", created_at: earlier, updated_at: earlier },
];

const accessRequests: Row[] = [
  { id: "request-001", requester: users[1], requester_user_id: users[1].id, resource_type: "item", resource_id: "kb-security", access_type: "read", reason: "Supporting the release risk review.", status: "pending", created_at: now },
  { id: "request-002", requester: users[2], requester_user_id: users[2].id, resource_type: "item", resource_id: "kb-product", access_type: "read", reason: "Quarterly architecture control review.", status: "approved", created_at: earlier },
  { id: "request-003", requester: users[3], requester_user_id: users[3].id, resource_type: "group", resource_id: "group-security", access_type: "member", reason: "Temporary audit support.", status: "denied", created_at: "2026-08-18T06:00:00.000Z" },
];

const policies: Row[] = [
  { id: "policy-product", name: "Product knowledge audience", resource_type: "item", resource_id: "kb-product", resource_title: "Product & Engineering", allowed_principal_tokens: ["group:product-engineering", "user:user-maya-chen"], denied_principal_tokens: [], status: "active", updated_at: now },
  { id: "policy-security", name: "Restricted security library", resource_type: "item", resource_id: "kb-security", resource_title: "Security & Compliance", allowed_principal_tokens: ["group:security-reviewers"], denied_principal_tokens: ["group:contractors"], status: "active", updated_at: earlier },
];

const audits: Row[] = [
  audit("audit-001", users[0], "plugin_connection.validated", "plugin_connection", connections[0].id, "success", now),
  audit("audit-002", users[1], "knowledge_base.sync_started", "item", "kb-product", "success", earlier),
  audit("audit-003", users[0], "access_request.approved", "access_request", "request-002", "success", "2026-08-23T08:20:00.000Z"),
  audit("audit-004", null, "ingestion.run_failed", "sync_run", "run-finance-failed", "failed", "2026-08-22T05:10:00.000Z"),
];

const state: Record<string, Row[]> = {
  items: [...collections, ...documents],
  "plugin-connections": connections,
  "plugin-bindings": bindings,
  "ingestion/jobs": runs,
  users,
  groups,
  roles,
  "access-requests": accessRequests,
  "acl-policies": policies,
  "audit-logs": audits,
  spaces: [{ id: "space-northstar", code: "northstar", name: "Northstar Intelligence", status: "active", created_at: "2026-03-01T00:00:00.000Z", updated_at: now }],
};

export async function mockAdminRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  await mockDelay(init.signal);
  const url = new URL(path, "https://mock.bothesis.local");
  const route = url.pathname.replace(/^\//, "");
  const method = (init.method ?? "GET").toUpperCase();
  const body = parseBody(init.body);

  if (method === "GET") return readRoute(route, url.searchParams) as T;
  return mutateRoute(route, method, body) as T;
}

export async function mockDatasourceUpload<T>(connectorId: string, file: File, options: { onProgress?: (percent: number) => void; signal?: AbortSignal }): Promise<T> {
  for (const progress of [18, 52, 84, 100]) {
    await mockDelay(options.signal, 80);
    options.onProgress?.(progress);
  }
  const target = state["plugin-bindings"].find((item) => item.connection_id === connectorId)?.target_item_id ?? "kb-security";
  const created = document(id("doc"), file.name, target, file.type.includes("pdf") ? "pdf" : "file", file.size, "ready", true, connectorId, connections.find((item) => item.id === connectorId)?.display_name ?? "Managed upload");
  state.items.unshift(created);
  return created as T;
}

function readRoute(route: string, params: URLSearchParams) {
  if (route === "overview") {
    return {
      tenant: { id: "tenant-northstar", code: "northstar", name: "Northstar Intelligence", status: "active", updated_at: now },
      metrics: { active_users: users.filter((item) => item.status === "active").length, active_plugin_connections: connections.filter((item) => item.status === "active").length, active_datasources: bindings.filter((item) => item.status === "active").length, items: state.items.length },
      attention: { failed_syncs: runs.filter((item) => item.status === "failed").length, pending_access_requests: accessRequests.filter((item) => item.status === "pending").length, failed_items: state.items.filter((item) => item.status === "failed").length },
      recent_activity: audits.slice(0, 4),
      generated_at: now,
    };
  }
  if (route === "plugins/capabilities") {
    return { plugins: [
      { plugin_key: "confluence", display_name: "Confluence", authentication_type: "api_token", capabilities: ["Sync", "Search", "Permissions"] },
      { plugin_key: "file", display_name: "Files", authentication_type: "managed", capabilities: ["Upload", "Extract", "Permissions"] },
    ] };
  }
  const itemMatch = route.match(/^items\/([^/]+)$/);
  if (itemMatch) return required(state.items.find((item) => item.id === itemMatch[1]), "Knowledge item");
  const accessMatch = route.match(/^collections\/([^/]+)\/access$/);
  if (accessMatch) return paginate(grants.filter((item) => item.item_id === accessMatch[1]), params);
  const list = state[route];
  if (list) return paginate(filterRows(list, params), params);
  throw new Error(`Mock Admin route is not implemented: GET /${route}`);
}

function mutateRoute(route: string, method: string, body: Row) {
  if (route === "collections" && method === "POST") {
    const created = collection(id("kb"), body.title || "Untitled knowledge base", body.metadata?.description ?? "", "pending", Boolean(body.inherit_access));
    state.items.unshift(created);
    return created;
  }
  const accessMatch = route.match(/^collections\/([^/]+)\/access$/);
  if (accessMatch && method === "PUT") {
    const created = { item_id: accessMatch[1], ...body, created_at: now, updated_at: now };
    grants.push(created);
    return created;
  }
  const createBindingMatch = route.match(/^plugin-connections\/([^/]+)\/bindings$/);
  if (createBindingMatch && method === "POST") {
    const created = binding(id("binding"), createBindingMatch[1], body.target_item_id, body.display_name, "active", body.schedule ?? null);
    created.config = body.config ?? {};
    state["plugin-bindings"].unshift(created);
    return created;
  }
  const syncMatch = route.match(/^plugin-bindings\/([^/]+)\/sync$/);
  if (syncMatch && method === "POST") {
    const selectedBinding = required(bindings.find((item) => item.id === syncMatch[1]), "Binding");
    const selectedConnection = required(connections.find((item) => item.id === selectedBinding.connection_id), "Connection");
    const created = run(id("run"), selectedBinding, selectedConnection, "running", 0, 0, 0, null, now);
    runs.unshift(created);
    const target = state.items.find((item) => item.id === selectedBinding.target_item_id);
    if (target) { target.status = "processing"; target.updated_at = now; }
    return created;
  }
  if (route === "plugin-connections" && method === "POST") {
    const created = { id: id("conn"), plugin_key: body.plugin_key, display_name: body.display_name, config: body.config ?? {}, credential_configured: Boolean(body.credentials) || body.plugin_key === "file", owner_type: "tenant", status: "draft", binding_count: 0, created_at: now, updated_at: now };
    connections.unshift(created);
    return created;
  }
  const validateMatch = route.match(/^plugin-connections\/([^/]+)\/validate$/);
  if (validateMatch && method === "POST") {
    const target = required(connections.find((item) => item.id === validateMatch[1]), "Connection");
    target.status = "active";
    target.credential_configured = true;
    target.updated_at = now;
    return target;
  }
  const retryItem = route.match(/^items\/([^/]+)\/retry$/);
  if (retryItem && method === "POST") return patchOne("items", retryItem[1], { status: "processing", updated_at: now });
  const runAction = route.match(/^ingestion\/jobs\/([^/]+)\/(cancel|retry)$/);
  if (runAction && method === "POST") return patchOne("ingestion/jobs", runAction[1], { status: runAction[2] === "cancel" ? "cancelled" : "pending" });
  const decision = route.match(/^access-requests\/([^/]+)\/decision$/);
  if (decision && method === "POST") return patchOne("access-requests", decision[1], { status: body.decision });
  const resource = route.match(/^(spaces|users|groups|roles|acl-policies|plugin-connections|items)\/([^/]+)$/);
  if (resource && method === "PATCH") return patchOne(resource[1], resource[2], { ...body, updated_at: now });
  if (resource && method === "DELETE") return tombstone(resource[1], resource[2]);
  if (["users", "groups", "roles", "access-requests", "acl-policies"].includes(route) && method === "POST") {
    const created: Row = { id: id(route.replace(/s$/, "")), ...body, status: body.status ?? "active", created_at: now, updated_at: now };
    if (route === "users") {
      created.membership = { role: roles.find((role) => role.id === body.role_id) };
      created.groups = groups.filter((group) => body.group_ids?.includes(group.id));
      created.last_login_at = null;
    }
    if (route === "groups") { created.principal_token = `group:${body.code}`; created.member_count = 0; }
    if (route === "roles") created.member_count = 0;
    if (route === "access-requests") { created.status = "pending"; created.requester = users.find((item) => item.id === body.requester_user_id); }
    state[route].unshift(created);
    return created;
  }
  throw new Error(`Mock Admin route is not implemented: ${method} /${route}`);
}

function filterRows(rows: Row[], params: URLSearchParams) {
  let result = rows.filter((item) => !item.deleted_at);
  for (const key of ["status", "item_type", "target_item_id"]) {
    const value = params.get(key);
    if (value) result = result.filter((item) => String(item[key]) === value);
  }
  const search = (params.get("search") ?? params.get("q") ?? "").trim().toLowerCase();
  if (search) result = result.filter((item) => JSON.stringify(item).toLowerCase().includes(search));
  return result;
}

function paginate(rows: Row[], params: URLSearchParams) {
  const page = Math.max(1, Number(params.get("page") ?? 1));
  const pageSize = Math.max(1, Number(params.get("page_size") ?? 20));
  return { items: rows.slice((page - 1) * pageSize, page * pageSize), total: rows.length, page, page_size: pageSize };
}

function patchOne(resource: string, itemId: string, patch: Row) {
  const target = required(state[resource]?.find((item) => item.id === itemId), resource);
  Object.assign(target, patch);
  return target;
}

function tombstone(resource: string, itemId: string) {
  const target = patchOne(resource, itemId, { deleted_at: now, status: "disabled", updated_at: now });
  return target;
}

function parseBody(body: BodyInit | null | undefined): Row {
  if (typeof body !== "string" || !body) return {};
  try { return JSON.parse(body) as Row; } catch { return {}; }
}

function required<T>(value: T | undefined, label: string): T {
  if (!value) throw new Error(`${label} was not found in mock data.`);
  return value;
}

function id(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
}

function mockDelay(signal?: AbortSignal | null, duration = 140) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("The request was cancelled.", "AbortError")); return; }
    const timer = setTimeout(resolve, duration);
    signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("The request was cancelled.", "AbortError")); }, { once: true });
  });
}

function collection(idValue: string, title: string, description: string, status: string, inheritAccess: boolean) {
  return { id: idValue, item_type: "collection", document_type: null, title, mime_type: null, size_bytes: null, parent_item_id: null, parent_relation: null, status, indexed: status === "ready", inherit_access: inheritAccess, metadata: { description, access_model: inheritAccess ? "mirror" : "custom" }, origins: [], created_at: "2026-06-01T03:00:00.000Z", updated_at: now };
}

function document(idValue: string, title: string, parent: string, kind: string, size: number, status: string, indexed: boolean, connectionId: string, connectionName: string) {
  const bindingId = ({ "kb-product": "binding-product", "kb-security": "binding-security", "kb-operations": "binding-operations", "kb-finance": "binding-finance" } as Record<string, string>)[parent] ?? "binding-managed";
  return { id: idValue, item_type: "document", document_type: kind, title, mime_type: kind === "pdf" ? "application/pdf" : "text/html", size_bytes: size, parent_item_id: parent, parent_relation: "contains", status, indexed, metadata: {}, origins: [{ id: `origin-${idValue}`, external_id: idValue, source_url: "https://northstar.example/knowledge", binding_id: bindingId, connection: { id: connectionId, display_name: connectionName, plugin_key: connectionId.includes("confluence") ? "confluence" : "file" } }], created_at: "2026-07-10T04:00:00.000Z", updated_at: now };
}

function binding(idValue: string, connectionId: string, targetId: string, name: string, status: string, schedule: Row | null) {
  return { id: idValue, connection_id: connectionId, target_item_id: targetId, display_name: name, config: { scope_mode: "all", include_scopes: [], exclude_scopes: [] }, checkpoint: { cursor: "mock-cursor" }, status, last_synced_at: earlier, last_indexed_at: earlier, schedule };
}

function run(idValue: string, bindingValue: Row, connection: Row, status: string, discovered: number, processed: number, chunks: number, error: string | null, created: string) {
  return { id: idValue, binding_id: bindingValue.id, trigger_type: status === "pending" ? "scheduled" : "manual", status, discovered_item_count: discovered, processed_item_count: processed, written_chunk_count: chunks, deleted_item_count: 0, error_code: error ? "VALIDATION_FAILED" : null, error_message: error, started_at: status === "pending" ? null : created, finished_at: ["completed", "failed", "cancelled"].includes(status) ? created : null, created_at: created, connection: { id: connection.id, display_name: connection.display_name, plugin_key: connection.plugin_key }, binding: { id: bindingValue.id, display_name: bindingValue.display_name, target_item_id: bindingValue.target_item_id } };
}

function user(idValue: string, email: string, name: string, role: Row, memberGroups: Row[], status: string, lastLogin: string) {
  return { id: idValue, email, display_name: name, membership: { role }, groups: memberGroups, status, last_login_at: lastLogin, created_at: "2026-04-01T00:00:00.000Z", updated_at: now };
}

function audit(idValue: string, actor: Row | null, action: string, resourceType: string, resourceId: string, outcome: string, created: string) {
  return { id: idValue, actor, action, resource_type: resourceType, resource_id: resourceId, outcome, created_at: created };
}
