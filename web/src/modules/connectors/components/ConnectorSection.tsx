import type { ConnectorDefinition } from "../catalog";
import type { ConnectorRegistryStatus } from "../types";
import { ConnectorCard } from "./ConnectorCard";

export interface ConnectorSectionItem {
  connector: ConnectorDefinition;
  connectionCount: number;
  status: ConnectorRegistryStatus;
}

export function ConnectorSection({
  description,
  items,
  onSelect,
  title,
}: {
  description?: string;
  items: ConnectorSectionItem[];
  onSelect: (connector: ConnectorDefinition) => void;
  title: string;
}) {
  const id = `connector-${title.toLocaleLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[0.9375rem] font-semibold tracking-[-0.01em] text-[var(--text)]" id={id}>{title}</h2>
          {description && <p className="mt-1 text-xs text-[var(--text-muted)]">{description}</p>}
        </div>
        <span className="text-xs tabular-nums text-[var(--text-muted)]">{items.length}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <ConnectorCard
            connectionCount={item.connectionCount}
            connector={item.connector}
            key={item.connector.provider}
            onClick={() => onSelect(item.connector)}
            status={item.status}
          />
        ))}
      </div>
    </section>
  );
}
