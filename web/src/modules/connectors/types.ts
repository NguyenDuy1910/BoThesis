import type { ConnectorProvider } from "./catalog";

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
