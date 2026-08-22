import { X } from "lucide-react";

import type { ChatConnector } from "../types";
import { ConnectorLogo } from "./ConnectorLogo";

export function SelectedPluginChips({
  connectors,
  onRemove,
}: {
  connectors: ChatConnector[];
  onRemove: (connectorId: string) => void;
}) {
  if (!connectors.length) return null;
  return (
    <div aria-label="Selected connectors" className="plugin-chips">
      {connectors.map((connector) => (
        <span className="plugin-chip" key={connector.id}>
          <ConnectorLogo provider={connector.provider} size="sm" />
          <span title={connector.display_name}>{connector.display_name}</span>
          <button aria-label={`Remove ${connector.display_name}`} onClick={() => onRemove(connector.id)} type="button">
            <X aria-hidden="true" size={12} />
          </button>
        </span>
      ))}
    </div>
  );
}
