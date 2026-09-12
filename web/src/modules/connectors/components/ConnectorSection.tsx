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
      <div className="mb-2.5">
        <h3
          className="text-[0.8125rem] font-semibold text-[var(--text-primary)]"
          id={id}
        >
          {title}
          <span className="ml-2 font-normal tabular-nums text-[var(--text-tertiary)]">
            {items.length}
          </span>
        </h3>
        {description && (
          <p className="mt-0.5 text-[0.75rem] text-[var(--text-tertiary)]">{description}</p>
        )}
      </div>
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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
