/**
 * The connector catalogue.
 *
 * Two things live here and they answer different questions.
 *
 * `presentation` is how a connector *looks* — its name, the one phrase saying
 * what it brings in, and the key that selects its brand mark. It is curated,
 * because a deployment's registry returns identifiers, not copy.
 *
 * `setup` is what a connector *needs* — the fields its connection and its
 * sources are built from. It mirrors the backend's connector registry: the
 * config keys land in `IntegrationConnection.config`, the credential keys are
 * encrypted into `IntegrationCredential`, and the scope keys become the
 * `IngestionSource.config` the connector runtime reads.
 *
 * What a deployment can actually connect is decided by the backend, not by
 * this file: `GET /admin/connectors/capabilities` is the source of truth, and
 * an entry here without a registration there is never offered. Adding a
 * connector to the product is a registration in the backend plus a row here —
 * never a new screen.
 */

export type ConnectorFieldKind = "text" | "url" | "email" | "secret" | "boolean";

export interface ConnectorField {
  name: string;
  label: string;
  kind: ConnectorFieldKind;
  required?: boolean;
  placeholder?: string;
  /** What the value is, in plain language. Never a sentence about the field. */
  help?: string;
  defaultValue?: string | boolean;
}

export interface ConnectorSetup {
  /** Non-secret values stored on the connection. */
  connection: readonly ConnectorField[];
  /** Secrets. They are written once and never read back. */
  credentials: readonly ConnectorField[];
  /** What a single source draws from the connection. */
  scope: readonly ConnectorField[];
  /**
   * Set when the deployment can hold the credentials itself. Selecting it
   * writes this config flag instead of asking anyone for a secret.
   */
  environmentCredentialKey?: string;
  /** Where to get a token, for the one field nobody can guess. */
  credentialHelpUrl?: string;
}

/**
 * What a connector is, for the page that introduces it.
 *
 * Only written for a connector this product actually implements. Describing
 * what an integration reads is a claim about behaviour, and there is nothing
 * to claim for a key the deployment has no adapter for — that page says it is
 * unavailable and stops there rather than advertising something that does not
 * run.
 */
export interface ConnectorOverview {
  /** One paragraph. What it is for, not what the screen is doing. */
  summary: string;
  /** What ends up in workspace knowledge. */
  reads: readonly string[];
  /** What the reader needs in hand before starting. */
  requires?: readonly string[];
}

export interface KnowledgeConnector {
  /** Matches the backend's `connector_key`. Also selects the brand mark. */
  key: string;
  name: string;
  description: string;
  overview?: ConnectorOverview;
  setup: ConnectorSetup;
}

const NO_SETUP: ConnectorSetup = { connection: [], credentials: [], scope: [] };

export const knowledgeConnectors: readonly KnowledgeConnector[] = [
  {
    key: "confluence",
    name: "Confluence",
    description: "Spaces, pages and attachments",
    overview: {
      summary:
        "Reads the spaces and pages your team already writes in Confluence, so answers can quote a policy or a runbook and cite the page it came from. Pages are re-read on a schedule, and an edit in Confluence reaches answers at the next sync.",
      reads: [
        "Pages in the spaces you select, and their child pages when you ask for them",
        "Page titles, body text and tables",
        "Attachments on those pages, where the format can be read",
      ],
      requires: [
        "An Atlassian account that can already open the content you want indexed",
        "An API token for that account, unless this deployment can sign you in to Atlassian directly",
      ],
    },
    setup: {
      connection: [
        {
          name: "wiki_base",
          label: "Site URL",
          kind: "url",
          required: true,
          placeholder: "https://your-team.atlassian.net/wiki",
          help: "The address you open Confluence at.",
        },
        {
          name: "is_cloud",
          label: "Atlassian Cloud",
          kind: "boolean",
          defaultValue: true,
          help: "Turn off for Confluence Server or Data Center.",
        },
      ],
      credentials: [
        {
          name: "confluence_username",
          label: "Account email",
          kind: "email",
          required: true,
          placeholder: "you@company.com",
          help: "The Atlassian account the token belongs to.",
        },
        {
          name: "confluence_access_token",
          label: "API token",
          kind: "secret",
          required: true,
          help: "Stored encrypted. It is never shown again after this step.",
        },
      ],
      scope: [
        {
          name: "space",
          label: "Space key",
          kind: "text",
          placeholder: "ENG",
          help: "Leave empty to read the whole site.",
        },
        {
          name: "page_id",
          label: "Page ID",
          kind: "text",
          help: "Narrows the space to one page and, optionally, its children.",
        },
        {
          name: "index_recursively",
          label: "Include child pages",
          kind: "boolean",
          defaultValue: false,
        },
      ],
      environmentCredentialKey: "use_environment_credentials",
      credentialHelpUrl: "https://id.atlassian.com/manage-profile/security/api-tokens",
    },
  },
  {
    key: "file",
    name: "Uploaded files",
    description: "Files added by workspace members",
    overview: {
      summary:
        "Holds the documents people upload directly to this workspace. Nothing is fetched from anywhere: a file is read once when it arrives, and stays until someone removes it.",
      reads: [
        "PDF, DOCX, XLSX, TXT and Markdown files uploaded to a collection",
      ],
    },
    setup: NO_SETUP,
  },
  {
    key: "google_drive",
    name: "Google Drive",
    description: "Files and shared drives",
    overview: {
      summary:
        "Reads the Drive files your team already works in, so answers can quote a spec or a spreadsheet and link back to it. You sign in to Google once; what gets indexed is whichever drives and folders you pick afterwards, and nothing else.",
      reads: [
        "Files in the drives and folders you select",
        "Google Docs, Sheets and Slides, plus PDF, DOCX, XLSX and text files",
        "The document text, tables, and who last changed it",
      ],
      requires: [
        "A Google account that can already open the files you want indexed",
      ],
    },
    setup: NO_SETUP,
  },
  { key: "notion", name: "Notion", description: "Pages and databases", setup: NO_SETUP },
  { key: "sharepoint", name: "SharePoint", description: "Sites and document libraries", setup: NO_SETUP },
  { key: "dropbox", name: "Dropbox", description: "Folders and shared files", setup: NO_SETUP },
  { key: "box", name: "Box", description: "Enterprise folders and files", setup: NO_SETUP },
  { key: "microsoft-365", name: "Microsoft 365", description: "OneDrive and Microsoft content", setup: NO_SETUP },
  { key: "github", name: "GitHub", description: "Repositories, docs and issues", setup: NO_SETUP },
  { key: "gitlab", name: "GitLab", description: "Projects, wikis and issues", setup: NO_SETUP },
  { key: "jira", name: "Jira", description: "Projects, issues and knowledge", setup: NO_SETUP },
  { key: "slack", name: "Slack", description: "Channels and selected conversations", setup: NO_SETUP },
  { key: "gmail", name: "Gmail", description: "Selected mailboxes and threads", setup: NO_SETUP },
  { key: "linear", name: "Linear", description: "Projects, issues and roadmaps", setup: NO_SETUP },
  { key: "asana", name: "Asana", description: "Projects, tasks and briefs", setup: NO_SETUP },
  { key: "website", name: "Website", description: "Public pages and sitemaps", setup: NO_SETUP },
];

/* Rows below `file` have no adapter in the backend registry, so a live
   deployment never offers them; they exist so the design preview can show what
   the directory looks like populated. */

const byKey = new Map(knowledgeConnectors.map((item) => [item.key, item]));
const byName = new Map(knowledgeConnectors.map((item) => [item.name.toLowerCase(), item]));

export function connectorByKey(key: string): KnowledgeConnector | undefined {
  return byKey.get(key.trim().toLowerCase());
}

/** Resolves a stored provider name to its catalogue entry. */
export function connectorByName(name: string): KnowledgeConnector | undefined {
  return byName.get(name.trim().toLowerCase());
}

export function connectorKeyFor(name: string): string {
  return (
    byKey.get(name.trim().toLowerCase())?.key
    ?? connectorByName(name)?.key
    ?? name.trim().toLowerCase().replaceAll(/\s+/g, "-")
  );
}

/** The catalogue entry for a key the backend knows but the catalogue does not. */
export function describeConnector(key: string, displayName?: string): KnowledgeConnector {
  return (
    connectorByKey(key)
    ?? { key, name: displayName ?? key, description: "", setup: NO_SETUP }
  );
}
