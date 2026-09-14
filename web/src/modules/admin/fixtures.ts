/**
 * Design-phase fixtures.
 *
 * The Workspace Architecture introduced five administrative surfaces that no
 * endpoint backs yet: Experience, Public Workspaces, Models & Capabilities,
 * Integrations and Usage. They are built against this module so the flow can
 * be reviewed end to end; when the API lands, each page swaps this import for
 * `useAdminQuery` and nothing else about the screen changes.
 *
 * Nothing here is written back. Every control on these pages is local state.
 */

export interface ExperienceSettings {
  workspaceName: string;
  accent: string;
  welcomeHeadline: string;
  welcomeBody: string;
  starterPrompts: string[];
  showStarterPrompts: boolean;
  showCapabilities: boolean;
  showSourceCount: boolean;
}

export const experienceFixture: ExperienceSettings = {
  workspaceName: "SPKT Assistant",
  accent: "indigo",
  welcomeHeadline: "What can I help you find?",
  welcomeBody:
    "Ask about policies, procedures and student services. Answers cite the documents they came from.",
  starterPrompts: [
    "Summarise the graduation procedure for the 2026 intake",
    "Which scholarships am I eligible for?",
    "What is the deadline to withdraw from a course?",
  ],
  showStarterPrompts: true,
  showCapabilities: true,
  showSourceCount: false,
};

export const accentOptions = [
  { value: "indigo", label: "Indigo" },
  { value: "teal", label: "Teal" },
  { value: "amber", label: "Amber" },
  { value: "rose", label: "Rose" },
];

export interface PublicWorkspace {
  id: string;
  name: string;
  summary: string;
  members: number;
  published: boolean;
  landing: boolean;
}

export const publicWorkspacesFixture: PublicWorkspace[] = [
  { id: "spkt", name: "SPKT Assistant", summary: "Student services, policies and academic procedure", members: 4210, published: true, landing: true },
  { id: "library", name: "Library Research", summary: "Catalogue search, citation help and interlibrary loans", members: 860, published: true, landing: false },
  { id: "it-help", name: "IT Help", summary: "Accounts, devices, network and software access", members: 1190, published: true, landing: false },
  { id: "finance", name: "Finance Operations", summary: "Budgets, procurement and reimbursement", members: 52, published: false, landing: false },
  { id: "hr", name: "People & Culture", summary: "Employment policy, leave and onboarding", members: 118, published: false, landing: false },
];

export interface PlatformModel {
  id: string;
  name: string;
  provider: string;
  context: string;
  tier: "frontier" | "balanced" | "fast";
  available: boolean;
  tenantsUsing: number;
}

export const modelsFixture: PlatformModel[] = [
  { id: "opus", name: "Claude Opus 5", provider: "Anthropic", context: "200K", tier: "frontier", available: true, tenantsUsing: 3 },
  { id: "sonnet", name: "Claude Sonnet 5", provider: "Anthropic", context: "200K", tier: "balanced", available: true, tenantsUsing: 11 },
  { id: "haiku", name: "Claude Haiku 4.5", provider: "Anthropic", context: "200K", tier: "fast", available: true, tenantsUsing: 9 },
  { id: "embed", name: "Voyage 3 Embeddings", provider: "Voyage AI", context: "32K", tier: "fast", available: true, tenantsUsing: 14 },
  { id: "local", name: "Qwen 3 32B", provider: "Self-hosted", context: "128K", tier: "balanced", available: false, tenantsUsing: 0 },
];

export interface PlatformCapability {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  note?: string;
}

export const capabilitiesFixture: PlatformCapability[] = [
  { id: "retrieval", name: "Document retrieval", description: "Ground answers in the tenant's indexed documents, with citations.", enabled: true },
  { id: "web", name: "Web search", description: "Reach public sources when the tenant's own knowledge does not answer.", enabled: false, note: "Leaves the tenant boundary. Off by default." },
  { id: "analysis", name: "File analysis", description: "Read a file the person attaches to a single conversation.", enabled: true },
  { id: "sql", name: "Governed SQL", description: "Answer from validated datasets and governed metrics.", enabled: false, note: "Requires a reviewed metric layer per tenant." },
];

export interface ConnectorAvailability {
  id: string;
  name: string;
  category: string;
  available: boolean;
  connections: number;
}

export const connectorsFixture: ConnectorAvailability[] = [
  { id: "gdrive", name: "Google Drive", category: "Files", available: true, connections: 7 },
  { id: "confluence", name: "Confluence", category: "Wiki", available: true, connections: 4 },
  { id: "jira", name: "Jira", category: "Work tracking", available: true, connections: 2 },
  { id: "slack", name: "Slack", category: "Messaging", available: false, connections: 0 },
  { id: "sharepoint", name: "SharePoint", category: "Files", available: true, connections: 3 },
  { id: "postgres", name: "PostgreSQL", category: "Database", available: false, connections: 0 },
];

export interface PlatformConnection {
  id: string;
  connector: string;
  tenant: string;
  scope: string;
  status: "healthy" | "syncing" | "failed" | "paused";
  lastSync: string;
}

export const connectionsFixture: PlatformConnection[] = [
  { id: "c1", connector: "Google Drive", tenant: "SPKT Assistant", scope: "Policies (shared drive)", status: "healthy", lastSync: "12 minutes ago" },
  { id: "c2", connector: "Confluence", tenant: "IT Help", scope: "IT space", status: "syncing", lastSync: "Running now" },
  { id: "c3", connector: "Google Drive", tenant: "Library Research", scope: "Catalogue exports", status: "failed", lastSync: "2 days ago" },
  { id: "c4", connector: "Jira", tenant: "IT Help", scope: "SERVICE project", status: "healthy", lastSync: "1 hour ago" },
  { id: "c5", connector: "SharePoint", tenant: "Finance Operations", scope: "Procurement", status: "paused", lastSync: "3 weeks ago" },
];

export interface TenantUsage {
  id: string;
  tenant: string;
  conversations: number;
  messages: number;
  documents: number;
  tokens: number;
  cost: number;
  trend: number;
}

export const usageFixture: TenantUsage[] = [
  { id: "spkt", tenant: "SPKT Assistant", conversations: 18420, messages: 96310, documents: 412, tokens: 214_800_000, cost: 1284.4, trend: 12 },
  { id: "it-help", tenant: "IT Help", conversations: 5210, messages: 24880, documents: 190, tokens: 58_200_000, cost: 349.2, trend: 4 },
  { id: "library", tenant: "Library Research", conversations: 3180, messages: 14020, documents: 640, tokens: 41_600_000, cost: 249.6, trend: -6 },
  { id: "finance", tenant: "Finance Operations", conversations: 410, messages: 1980, documents: 88, tokens: 5_900_000, cost: 35.4, trend: 2 },
  { id: "hr", tenant: "People & Culture", conversations: 260, messages: 1140, documents: 54, tokens: 3_100_000, cost: 18.6, trend: 0 },
];

export const usagePeriods = [
  { value: "30d", label: "Last 30 days" },
  { value: "7d", label: "Last 7 days" },
  { value: "24h", label: "Last 24 hours" },
];
