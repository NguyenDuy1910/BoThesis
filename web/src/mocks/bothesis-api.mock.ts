import type { AuthSession } from "@/lib/auth/session";
import {
  capabilitiesFixture, connectionsFixture, connectorsFixture, experienceFixture,
  modelsFixture, publicWorkspacesFixture, usageFixture,
  type ExperienceSettings,
} from "@/modules/admin/fixtures";
import { knowledgeWorkspaceRepository } from "@/modules/knowledge/workspace-repository";
import type { WorkspaceKnowledgeDocument } from "@/modules/knowledge/workspace-repository";

/** The design preview's only public data boundary. No HTTP or browser persistence. */
export const previewMode = process.env.NEXT_PUBLIC_BOTHESIS_DATA_MODE !== "live";

export interface Workspace {
  id: string; name: string; organization: string; description: string;
  member: boolean; discoverable: boolean; access: "members" | "everyone";
  status: "active" | "suspended"; isDefault: boolean;
}
export interface Member {
  id: string; name: string; email: string; role: string; status: "active" | "invited" | "suspended";
  groups: string[]; workspaceId: string;
}
export interface AccessGroup { id: string; name: string; description: string; members: number; role: string }
export interface AccessRole { id: string; name: string; description: string; permissions: string[]; builtIn: boolean }
export interface AccessPolicy {
  workspaceAccess: "members" | "everyone";
  discoverable: boolean;
  platformDefault: boolean;
  invitations: "admins" | "members";
  sourcePermissions: boolean;
  guestAccess: boolean;
}
export interface ActivityEvent { id: string; actor: string; action: string; resource: string; workspace: string; time: string; status: "success" | "warning" | "danger" }
export interface Source {
  id: string; name: string; provider: string; scope: string; documents: number;
  status: "healthy" | "syncing" | "failed" | "paused"; lastSync: string;
}
export interface SyncRun { id: string; source: string; time: string; status: "complete" | "running" | "failed"; added: number; updated: number; error?: string }
export interface AgentSettings {
  name: string; description: string; instructions: string; model: string; temperature: number;
  citations: boolean; knowledgeOnly: boolean; askClarification: boolean; web: boolean;
  analysis: boolean; artifacts: boolean; sql: boolean; approval: boolean; tools: string[];
}
export interface WorkspaceExperience extends ExperienceSettings {
  appearance: "system" | "light" | "dark"; background: "plain" | "soft" | "gradient"; icon: string;
}
export interface LibraryDocument extends WorkspaceKnowledgeDocument { saved: boolean; uploaded: boolean }
export interface LibraryCollection { id: string; name: string; description: string }
let libraryCollections: LibraryCollection[] = [
  { id: "thesis", name: "Thesis research", description: "Personal collection" },
  { id: "policies", name: "Policies to review", description: "Personal collection" },
  { id: "templates", name: "Templates", description: "Personal collection" },
  { id: "saved", name: "Saved from workspace", description: "Saved items" },
];
let libraryDocuments: LibraryDocument[] = [
  { id: "travel-policy", title: "Travel reimbursement policy.pdf", kind: "pdf", state: "indexed", collection: "Policies to review", source: "SPKT Assistant", updatedLabel: "Sep 12", size: "1.1 MB", pagesLabel: "18 pages", saved: true, uploaded: false, original: ["SPKT BUSINESS TRAVEL POLICY", "SECTION 3 — REIMBURSEMENT", "3.1 Eligible expenses", "Employees may claim reasonable transport, accommodation and meal expenses incurred for approved university business travel.", "Personal upgrades and companion expenses are not reimbursable.", "3.2 Submission deadline", "Submit the reimbursement request with supporting receipts within 30 calendar days after the trip. Claims submitted later require manager approval."], agentView: [] },
  { id: "travel-guide", title: "Manager travel guide.docx", kind: "document", state: "indexed", collection: "Policies to review", source: "Uploaded by you", updatedLabel: "Sep 11", size: "284 KB", pagesLabel: "9 pages", saved: false, uploaded: true, original: ["Manager travel guide", "Before approving a trip", "Check the business purpose, expected budget and travel dates. Confirm that the employee understands which receipts to retain.", "After the trip", "Review the itemized claim and supporting receipts before forwarding to Finance."], agentView: [] },
  { id: "travel-template", title: "Travel request template.docx", kind: "document", state: "indexed", collection: "Templates", source: "Uploaded by you", updatedLabel: "Sep 10", size: "42 KB", pagesLabel: "2 pages", saved: false, uploaded: true, original: ["Travel request", "Employee: ____________________", "Destination and dates: ____________________", "Business purpose: ____________________", "Estimated cost and approval: ____________________"], agentView: [] },
  { id: "thesis-checklist", title: "Thesis submission checklist.pdf", kind: "pdf", state: "indexed", collection: "Thesis research", source: "Uploaded by you", updatedLabel: "Sep 9", size: "320 KB", pagesLabel: "4 pages", saved: false, uploaded: true, original: ["Thesis submission checklist", "Confirm the submission date with your department.", "Include the signed supervisor approval and the final thesis manuscript.", "Verify the required format and citation style before submitting."], agentView: [] },
  { id: "scholarships", title: "Scholarship criteria.xlsx", kind: "spreadsheet", state: "indexed", collection: "Saved from workspace", source: "SPKT Assistant", updatedLabel: "Sep 8", size: "96 KB", pagesLabel: "6 sheets", saved: true, uploaded: false, original: ["Scholarship criteria", "Award | Eligibility | Review owner", "Merit award | GPA and conduct | Student Services", "Research grant | Approved proposal | Research Office"], agentView: [] },
  { id: "review-notes", title: "Policy review notes.md", kind: "document", state: "indexed", collection: "Policies to review", source: "Uploaded by you", updatedLabel: "Sep 7", size: "12 KB", pagesLabel: "1 page", saved: false, uploaded: true, original: ["Policy review notes", "Compare the travel guide against the approved reimbursement policy.", "Questions for Finance: supporting documents, approval exceptions and submission deadlines."], agentView: [] },
  { id: "restricted-notes", title: "Internal budget planning.pdf", kind: "pdf", state: "restricted", collection: "Saved from workspace", source: "Vikki", updatedLabel: "Sep 6", size: "510 KB", pagesLabel: "8 pages", saved: true, uploaded: false, original: [], agentView: [] },
];
const knowledgeDocuments = new Map<string, WorkspaceKnowledgeDocument[]>();
async function documentsForWorkspace() {
  const id = workspaceId();
  if (!knowledgeDocuments.has(id)) knowledgeDocuments.set(id, (await knowledgeWorkspaceRepository.getSnapshot()).documents);
  return knowledgeDocuments.get(id)!;
}
function uploadedDocument(file: File, collection: string): WorkspaceKnowledgeDocument {
  const extension = file.name.split(".").pop()?.toLowerCase();
  const kind = extension === "pdf" ? "pdf" : ["xlsx", "xls", "csv"].includes(extension ?? "") ? "spreadsheet" : ["docx", "txt", "md"].includes(extension ?? "") ? "document" : "unsupported";
  return { id: crypto.randomUUID(), title: file.name, kind, state: kind === "unsupported" ? "failed" : "indexed", collection, source: "Uploaded by you", updatedLabel: "Just now", size: Math.max(1, Math.round(file.size / 1024)) + " KB", pagesLabel: "1 page", original: [file.name, "This uploaded file is available in your local preview session. Document parsing will be supplied by the file service."], agentView: ["Indexed content", "Preview content is simulated in this frontend phase."] };
}

let workspaces: Workspace[] = [
  { id: "spkt", name: "SPKT Assistant", organization: "SPKT University", description: "Admissions, academic regulations and graduation procedures.", member: true, discoverable: true, access: "everyone", status: "active", isDefault: true },
  { id: "vikki", name: "Vikki", organization: "Vikki Bank", description: "Banking policies, operations and internal knowledge.", member: true, discoverable: false, access: "members", status: "active", isDefault: false },
  { id: "engineering", name: "AI Engineering", organization: "BoThesis", description: "Engineering guides and the platform handbook.", member: true, discoverable: false, access: "members", status: "active", isDefault: false },
  { id: "legal", name: "Legal Research", organization: "BoThesis", description: "Research legislation and compare source material.", member: false, discoverable: true, access: "everyone", status: "active", isDefault: false },
  { id: "research", name: "BoThesis Research", organization: "BoThesis", description: "Explore research, papers and technical references.", member: false, discoverable: true, access: "everyone", status: "active", isDefault: false },
  { id: "student", name: "Student Assistant", organization: "SPKT University", description: "Everyday help for students at SPKT.", member: false, discoverable: true, access: "everyone", status: "active", isDefault: false },
];
let session: AuthSession | null = makeSession("spkt");
const listeners = new Set<() => void>();
let revision = 0;
function changed() { revision += 1; listeners.forEach((listener) => listener()); }
async function reply<T>(value: T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  return structuredClone(value);
}
function makeSession(workspaceId: string): AuthSession {
  const workspace = workspaces.find((item) => item.id === workspaceId)!;
  return {
    access_token: "frontend-preview-only", token_type: "bearer", expires_at: "2099-01-01T00:00:00Z",
    user_id: "duy", display_name: "Duy Nguyen", email: "duy.nguyen@hcmute.edu.vn",
    active_tenant_id: workspaceId, permissions: workspace.member ? ["admin"] : ["knowledge.read"],
    platform_scopes: ["root_admin"],
    tenants: workspaces.map((item) => ({ id: item.id, code: item.id, name: item.name, role_id: item.member ? "admin" : null, role_code: item.member ? "admin" : "visitor", permissions: item.member ? ["admin"] : ["knowledge.read"] })),
  };
}
let members: Member[] = [
  { id: "duy", name: "Duy Nguyen", email: "duy.nguyen@hcmute.edu.vn", role: "Owner", status: "active", groups: ["Administrators"], workspaceId: "spkt" },
  { id: "linh", name: "Linh Tran", email: "linh.tran@hcmute.edu.vn", role: "Admin", status: "active", groups: ["Academic Affairs"], workspaceId: "spkt" },
  { id: "minh", name: "Minh Pham", email: "minh.pham@hcmute.edu.vn", role: "Editor", status: "active", groups: ["Student Services"], workspaceId: "spkt" },
  { id: "an", name: "An Le", email: "an.le@hcmute.edu.vn", role: "Member", status: "invited", groups: [], workspaceId: "spkt" },
  { id: "mai", name: "Mai Nguyen", email: "mai.nguyen@vikki.vn", role: "Admin", status: "active", groups: ["Operations"], workspaceId: "vikki" },
];
let groups: AccessGroup[] = [
  { id: "academic", name: "Academic Affairs", description: "Academic policies and procedures", members: 8, role: "Editor" },
  { id: "services", name: "Student Services", description: "Student support and resources", members: 12, role: "Member" },
  { id: "admins", name: "Administrators", description: "Workspace administration", members: 2, role: "Admin" },
];
let roles: AccessRole[] = [
  { id: "owner", name: "Owner", description: "Full workspace control", permissions: ["Manage workspace", "Manage access", "Manage knowledge", "Configure agent"], builtIn: true },
  { id: "admin", name: "Admin", description: "Manage configuration, knowledge and access", permissions: ["Manage access", "Manage knowledge", "Configure agent"], builtIn: true },
  { id: "editor", name: "Editor", description: "Manage workspace knowledge", permissions: ["Manage knowledge", "Use workspace"], builtIn: true },
  { id: "member", name: "Member", description: "Chat and use workspace knowledge", permissions: ["Use workspace"], builtIn: true },
];
const agentDefault: AgentSettings = {
  name: "SPKT Assistant", description: "Academic guidance grounded in SPKT knowledge.",
  instructions: "You are SPKT Assistant. Help students and staff with academic regulations, admissions and graduation procedures. Ground factual answers in the workspace's knowledge and cite the source. If evidence is missing, say so and ask a clarifying question. Never invent a deadline or policy.",
  model: "gpt-5.6", temperature: 0.3, citations: true, knowledgeOnly: true,
  askClarification: true, web: false, analysis: true, artifacts: true, sql: false, approval: true,
  tools: ["Search workspace knowledge", "Read document", "Create document"],
};
const agents = new Map<string, AgentSettings>();
const experiences = new Map<string, WorkspaceExperience>();
const accessPolicies = new Map<string, AccessPolicy>();
const platform = {
  models: structuredClone(modelsFixture), capabilities: structuredClone(capabilitiesFixture),
  integrations: structuredClone(connectorsFixture), connections: structuredClone(connectionsFixture),
  publicWorkspaces: structuredClone(publicWorkspacesFixture), usage: structuredClone(usageFixture),
};
let events: ActivityEvent[] = [
  { id: "e1", actor: "Linh Tran", action: "Updated access policy", resource: "Workspace access", workspace: "spkt", time: "Today, 09:42", status: "success" },
  { id: "e2", actor: "Google Drive", action: "Sync completed", resource: "Academic policies", workspace: "spkt", time: "Today, 09:30", status: "success" },
  { id: "e3", actor: "Duy Nguyen", action: "Saved agent instructions", resource: "Agent", workspace: "spkt", time: "Yesterday, 16:20", status: "success" },
  { id: "e4", actor: "SharePoint", action: "Source authorization expired", resource: "Research archive", workspace: "spkt", time: "Yesterday, 14:10", status: "danger" },
  { id: "e5", actor: "Mai Nguyen", action: "Invited a workspace member", resource: "Members", workspace: "vikki", time: "Yesterday, 11:25", status: "success" },
];
const sourceStores = new Map<string, Source[]>();
const runStores = new Map<string, SyncRun[]>();
const workspaceId = () => session?.active_tenant_id ?? "spkt";
function sourceData() {
  const id = workspaceId();
  if (!sourceStores.has(id)) sourceStores.set(id, [
    { id: `${id}-drive`, name: "Academic policies", provider: "Google Drive", scope: "Policies / Shared drive", documents: 214, status: "healthy", lastSync: "12 minutes ago" },
    { id: `${id}-wiki`, name: "Student services", provider: "Confluence", scope: "Student Services space", documents: 156, status: "healthy", lastSync: "1 hour ago" },
    { id: `${id}-sharepoint`, name: "Research archive", provider: "SharePoint", scope: "Research / Documents", documents: 42, status: "failed", lastSync: "2 days ago" },
  ]);
  return sourceStores.get(id)!;
}
function record(action: string, resource: string) {
  events = [{ id: crypto.randomUUID(), actor: session?.display_name ?? "Duy Nguyen", action, resource, workspace: workspaceId(), time: "Just now", status: "success" }, ...events];
  changed();
}

export const mockApi = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  revision: () => revision,
  session: {
    current: () => session,
    async signIn() { session = makeSession("spkt"); changed(); return reply(session); },
    signOut() { session = null; changed(); },
    async switchWorkspace(id: string) {
      const workspace = workspaces.find((item) => item.id === id);
      if (!workspace || workspace.status !== "active") throw new Error("Access to this workspace is no longer available.");
      const name = session?.display_name;
      session = { ...makeSession(id), display_name: name ?? "Duy Nguyen" };
      changed(); return reply(session);
    },
    async updateProfile(name: string) {
      if (!session || !name.trim()) throw new Error("Enter your display name.");
      session = { ...session, display_name: name.trim() }; changed(); return reply(session);
    },
  },
  workspaces: {
    list: () => reply(workspaces),
    get: () => reply(workspaces.find((item) => item.id === workspaceId())!),
    async save(id: string, patch: Partial<Workspace>) {
      workspaces = workspaces.map((item) => ({ ...item, ...(patch.isDefault ? { isDefault: false } : {}), ...(item.id === id ? patch : {}) }));
      if (session) session = { ...session, tenants: session.tenants.map((item) => ({ ...item, name: workspaces.find((w) => w.id === item.id)?.name ?? item.name })) };
      record("Updated workspace", id); return reply(workspaces.find((item) => item.id === id)!);
    },
    async create(name: string, organization: string) {
      const item: Workspace = { id: crypto.randomUUID(), name, organization, description: "", member: true, discoverable: false, access: "members", status: "active", isDefault: false };
      workspaces = [...workspaces, item]; record("Created tenant", name); return reply(item);
    },
  },
  access: {
    members: (all = false) => reply(members.filter((item) => all || item.workspaceId === workspaceId())),
    groups: () => reply(groups), roles: () => reply(roles),
    policy: () => {
      const workspace = workspaces.find((item) => item.id === workspaceId())!;
      return reply(accessPolicies.get(workspaceId()) ?? { workspaceAccess: workspace.access, discoverable: workspace.discoverable, platformDefault: workspace.isDefault, invitations: "admins" as const, sourcePermissions: true, guestAccess: false });
    },
    async savePolicy(policy: AccessPolicy) {
      accessPolicies.set(workspaceId(), structuredClone(policy));
      workspaces = workspaces.map((item) => item.id === workspaceId() ? { ...item, access: policy.workspaceAccess, discoverable: policy.discoverable } : item);
      record("Updated access policy", "Workspace access"); return reply(policy);
    },
    async saveMember(member: Member) { members = [...members.filter((item) => item.id !== member.id), member]; record("Updated member", member.name); return reply(member); },
    async saveGroup(group: AccessGroup) { groups = [...groups.filter((item) => item.id !== group.id), group]; record("Updated group", group.name); return reply(group); },
    async saveRole(role: AccessRole) { roles = [...roles.filter((item) => item.id !== role.id), role]; record("Updated role", role.name); return reply(role); },
  },
  agent: {
    get: () => reply(agents.get(workspaceId()) ?? { ...agentDefault, name: workspaces.find((item) => item.id === workspaceId())!.name }),
    async save(value: AgentSettings) { agents.set(workspaceId(), structuredClone(value)); record("Saved agent configuration", "Agent"); return reply(value); },
  },
  experience: {
    get: () => reply(experiences.get(workspaceId()) ?? { ...experienceFixture, workspaceName: workspaces.find((item) => item.id === workspaceId())!.name, welcomeHeadline: "How can I help today?", appearance: "system" as const, background: "plain" as const, icon: "" }),
    async save(value: WorkspaceExperience) { experiences.set(workspaceId(), structuredClone(value)); record("Saved experience", "Experience"); return reply(value); },
  },
  knowledge: {
    documents: async () => reply(await documentsForWorkspace()),
    async upload(file: File) {
      if (file.size > 25_000_000) throw new Error("Upload failed. Choose a file smaller than 25 MB.");
      const document = uploadedDocument(file, "Uploaded files");
      (await documentsForWorkspace()).unshift(document); record("Uploaded document", file.name); return reply(document);
    },
    async reindex(id: string) {
      const document = (await documentsForWorkspace()).find((item) => item.id === id);
      if (!document) throw new Error("Document not found.");
      document.state = "indexing"; changed();
      await new Promise((resolve) => setTimeout(resolve, 1200));
      document.state = document.kind === "unsupported" ? "failed" : "indexed"; changed();
    },
    sources: () => reply(sourceData()),
    runs: () => reply(runStores.get(workspaceId()) ?? [{ id: "run-initial", source: "Academic policies", time: "Today, 09:30", status: "complete" as const, added: 3, updated: 8 }]),
    async addSource(provider: string, name: string) {
      const source: Source = { id: crypto.randomUUID(), name, provider, scope: "Selected workspace content", documents: 0, status: "healthy", lastSync: "Not synced yet" };
      sourceData().push(source); record("Added source", name); return reply(source);
    },
    async sync(id: string) {
      const source = sourceData().find((item) => item.id === id);
      if (!source) throw new Error("This source is no longer available.");
      source.status = "syncing"; changed();
      await new Promise((resolve) => setTimeout(resolve, 1600));
      source.status = "healthy"; source.lastSync = "Just now";
      const runs = runStores.get(workspaceId()) ?? [];
      runStores.set(workspaceId(), [{ id: crypto.randomUUID(), source: source.name, time: "Just now", status: "complete", added: 2, updated: 4 }, ...runs]);
      record("Sync completed", source.name); return reply(source);
    },
    async pause(id: string) { const source = sourceData().find((item) => item.id === id); if (source) source.status = "paused"; changed(); },
  },
  platform: {
    tenants: () => reply(workspaces), users: () => reply(members), audit: () => reply(events),
    system: () => reply({
      status: "healthy" as const,
      checkedAt: "Just now",
      version: "2026.9.14-preview",
      region: "Southeast Asia",
      services: [
        { id: "api", name: "Application API", status: "healthy" as const, latency: 42, required: true },
        { id: "index", name: "Knowledge index", status: "healthy" as const, latency: 68, required: true },
        { id: "storage", name: "Document storage", status: "healthy" as const, latency: 31, required: true },
        { id: "workflow", name: "Sync workflows", status: "warning" as const, latency: 184, required: false },
      ],
    }),
    models: () => reply(platform.models), capabilities: () => reply(platform.capabilities),
    integrations: () => reply(platform.integrations), connections: () => reply(platform.connections),
    publicWorkspaces: () => reply(platform.publicWorkspaces), usage: () => reply(platform.usage),
    async saveModels(value: typeof platform.models) { platform.models = structuredClone(value); record("Updated model availability", "Models"); },
    async saveCapabilities(value: typeof platform.capabilities) { platform.capabilities = structuredClone(value); record("Updated capabilities", "Capabilities"); },
    async saveIntegrations(value: typeof platform.integrations) { platform.integrations = structuredClone(value); record("Updated integrations", "Integrations"); },
    async savePublicWorkspaces(value: typeof platform.publicWorkspaces) { platform.publicWorkspaces = structuredClone(value); record("Updated publishing", "Public workspaces"); },
  },
  library: {
    list: () => reply(libraryDocuments), collections: () => reply(libraryCollections),
    async save(id: string, patch: Partial<Pick<LibraryDocument, "saved" | "collection" | "title">>) { libraryDocuments = libraryDocuments.map((item) => item.id === id ? { ...item, ...patch } : item); changed(); },
    async createCollection(name: string) { const item = { id: crypto.randomUUID(), name, description: "Personal collection" }; libraryCollections = [...libraryCollections, item]; changed(); return reply(item); },
    async upload(file: File, collection = "") {
      if (file.size > 25_000_000) throw new Error("Upload failed. Choose a file smaller than 25 MB and try again.");
      const document: LibraryDocument = { ...uploadedDocument(file, collection), saved: false, uploaded: true };
      if (["text/plain", "text/markdown", "text/csv"].includes(file.type)) document.original = (await file.text()).split("\n").slice(0, 100);
      libraryDocuments = [document, ...libraryDocuments]; changed(); return reply(document);
    },
    async addNote(title: string, content: string, collection = "") {
      const document: LibraryDocument = { id: crypto.randomUUID(), title, kind: "document", state: "indexed", collection, source: "Created by you", updatedLabel: "Just now", size: "1 KB", pagesLabel: "1 page", saved: false, uploaded: true, original: [title, content], agentView: [] };
      libraryDocuments = [document, ...libraryDocuments]; changed(); return reply(document);
    },
  },
  activity: { list: (all = false) => reply(events.filter((item) => all || item.workspace === workspaceId())) },
};
