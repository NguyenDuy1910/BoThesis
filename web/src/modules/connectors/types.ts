import type { ConnectorProvider } from "./catalog";

export interface ConnectorConnection {
  id: string;
  provider: ConnectorProvider | string;
  display_name: string;
  status: string;
  scopes?: Array<{
    id: string;
    display_name?: string | null;
    scope_type?: string | null;
    document_count?: number;
    last_synced_at?: string | null;
    latest_run?: { status?: string } | null;
  }>;
  last_synced_at?: string | null;
}

export interface ChatConnector {
  id: string;
  provider: ConnectorProvider | string;
  display_name: string;
  status: "active";
  capabilities: string[];
}

export type ConnectorRegistryStatus =
  | "connected"
  | "syncing"
  | "failed"
  | "available"
  | "disabled"
  | "needs_setup"
  | "unavailable";

export type ChatConnectorMode = "auto" | "selected" | "off";
