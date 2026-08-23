import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  Cloud,
  Code2,
  Database,
  FileUp,
  GitBranch,
  Mail,
  MessagesSquare,
  Network,
  Orbit,
  TableProperties,
  Webhook,
} from "lucide-react";

export type ConnectorCategory =
  | "knowledge"
  | "productivity"
  | "engineering"
  | "communication"
  | "database"
  | "storage";

export type ConnectorProvider =
  | "confluence"
  | "google_drive"
  | "jira"
  | "file"
  | "notion"
  | "sharepoint"
  | "slack"
  | "s3"
  | "onedrive"
  | "gmail"
  | "outlook"
  | "github"
  | "gitlab"
  | "linear"
  | "postgresql"
  | "mysql"
  | "snowflake"
  | "bigquery"
  | "mongodb"
  | "elasticsearch"
  | "cloudflare_r2"
  | "rest_api"
  | "webhook";

export interface ConnectorDefinition {
  provider: ConnectorProvider;
  name: string;
  description: string;
  category: ConnectorCategory;
  featured?: boolean;
  capabilities: readonly string[];
  authentication: string;
  icon?: LucideIcon;
  color: string;
}

/**
 * Product-level connector definitions. Runtime availability and configured
 * instances always come from the API; this catalog only owns stable display
 * metadata and can grow without changing registry rendering.
 */
export const connectorDefinitions: readonly ConnectorDefinition[] = [
  connector("confluence", "Confluence", "Spaces, pages, and governed team knowledge", "knowledge", "#1868DB", ["Search", "Sync", "Permissions"], "API token or OAuth", true),
  connector("google_drive", "Google Drive", "Shared drives, folders, and business files", "storage", "#4285F4", ["Search", "Sync", "Folder scope"], "Google OAuth", true),
  connector("jira", "Jira", "Projects, issues, comments, and delivery context", "engineering", "#2684FF", ["Search", "Sync", "Project scope"], "Atlassian OAuth", true),
  connector("file", "File Upload", "Upload governed documents directly to BoThesis", "knowledge", "#6157D9", ["Upload", "Index", "Citations"], "Workspace access", true, FileUp),
  connector("slack", "Slack", "Channels, threads, and operational conversations", "communication", "#4A154B", ["Search", "Sync", "Channel scope"], "Slack OAuth", true, MessagesSquare),
  connector("notion", "Notion", "Workspace pages, databases, and team docs", "knowledge", "#111111", ["Search", "Sync", "Page scope"], "Notion OAuth", true, TableProperties),
  connector("sharepoint", "SharePoint", "Sites, libraries, lists, and team content", "knowledge", "#038387", ["Search", "Sync", "Site scope"], "Microsoft OAuth", true, Boxes),
  connector("s3", "Amazon S3", "Buckets and object-based enterprise knowledge", "storage", "#FF9900", ["Sync", "Prefix scope", "Metadata"], "IAM role", true, Cloud),
  connector("onedrive", "OneDrive", "Personal and shared Microsoft 365 files", "storage", "#0078D4", ["Search", "Sync", "Folder scope"], "Microsoft OAuth", false, Cloud),
  connector("gmail", "Gmail", "Mailboxes and approved email knowledge", "communication", "#EA4335", ["Search", "Sync", "Label scope"], "Google OAuth", false, Mail),
  connector("outlook", "Outlook", "Microsoft 365 mail and shared mailboxes", "communication", "#0078D4", ["Search", "Sync", "Mailbox scope"], "Microsoft OAuth", false, Mail),
  connector("github", "GitHub", "Repositories, issues, pull requests, and discussions", "engineering", "#24292F", ["Search", "Sync", "Repository scope"], "GitHub App", false, Code2),
  connector("gitlab", "GitLab", "Projects, merge requests, issues, and wikis", "engineering", "#FC6D26", ["Search", "Sync", "Project scope"], "OAuth or token", false, GitBranch),
  connector("linear", "Linear", "Issues, projects, cycles, and product context", "engineering", "#5E6AD2", ["Search", "Sync", "Team scope"], "Linear OAuth", false, Orbit),
  connector("postgresql", "PostgreSQL", "Governed relational data and approved schemas", "database", "#336791", ["Query", "Schema", "Lineage"], "Secret reference", false, Database),
  connector("mysql", "MySQL", "Approved databases, tables, and business records", "database", "#4479A1", ["Query", "Schema", "Lineage"], "Secret reference", false, Database),
  connector("snowflake", "Snowflake", "Governed warehouse datasets and semantic assets", "database", "#29B5E8", ["Query", "Schema", "Lineage"], "Key pair or OAuth", false, Database),
  connector("bigquery", "BigQuery", "Google Cloud datasets and approved analytics", "database", "#4285F4", ["Query", "Schema", "Lineage"], "Service account", false, Database),
  connector("mongodb", "MongoDB", "Collections and approved document data", "database", "#47A248", ["Query", "Schema", "Lineage"], "Secret reference", false, Database),
  connector("elasticsearch", "Elasticsearch", "Search indices and operational knowledge", "database", "#005571", ["Search", "Index scope", "Metadata"], "API key", false, Network),
  connector("cloudflare_r2", "Cloudflare R2", "S3-compatible object storage and archives", "storage", "#F38020", ["Sync", "Prefix scope", "Metadata"], "API token", false, Cloud),
  connector("rest_api", "REST API", "Bring a governed HTTP API into the platform", "productivity", "#5865F2", ["Fetch", "Schema", "Authentication"], "Configurable", false, Network),
  connector("webhook", "Webhook", "Receive verified events from approved systems", "productivity", "#6B7280", ["Receive", "Verify", "Audit"], "Signing secret", false, Webhook),
];

export const connectorCategories: ReadonlyArray<{ id: ConnectorCategory; label: string }> = [
  { id: "knowledge", label: "Knowledge" },
  { id: "productivity", label: "Productivity" },
  { id: "engineering", label: "Engineering" },
  { id: "communication", label: "Communication" },
  { id: "database", label: "Database" },
  { id: "storage", label: "Storage" },
];

export function connectorDefinition(provider: string) {
  return connectorDefinitions.find((definition) => definition.provider === provider);
}

function connector(
  provider: ConnectorProvider,
  name: string,
  description: string,
  category: ConnectorCategory,
  color: string,
  capabilities: readonly string[],
  authentication: string,
  featured: boolean,
  icon?: LucideIcon,
): ConnectorDefinition {
  return {
    provider,
    name,
    description,
    category,
    color,
    capabilities,
    authentication,
    featured,
    icon,
  };
}
