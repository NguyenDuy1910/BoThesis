import { ArrowUpRight, Plus } from "lucide-react";

import { cn } from "@/lib/cn";
import type { ConnectorDefinition } from "../catalog";
import type { ConnectorRegistryStatus } from "../types";
import { ConnectionStatusBadge } from "./ConnectionStatusBadge";
import { ConnectorLogo } from "./ConnectorLogo";

export function ConnectorCard({
  connector,
  connectionCount,
  onClick,
  status,
}: {
  connector: ConnectorDefinition;
  connectionCount: number;
  onClick: () => void;
  status: ConnectorRegistryStatus;
}) {
  const action = status === "connected" || status === "disabled" || status === "needs_setup"
    ? "Manage"
    : status === "available" ? "Connect" : "View";
  return (
    <button
      aria-haspopup="dialog"
      className={cn(
        "connector-card group relative flex min-h-44 w-full cursor-pointer flex-col items-start rounded-2xl bg-[var(--surface)] p-4 text-left",
        "ring-1 ring-inset ring-[color-mix(in_srgb,var(--border)_72%,transparent)]",
        "transition-[transform,box-shadow,background-color] duration-[180ms] ease-[var(--ease-standard)]",
        "hover:-translate-y-0.5 hover:bg-[var(--surface-raised)] hover:shadow-[0_12px_30px_rgb(15_23_42/0.085)]",
        "active:translate-y-0 active:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2",
        "motion-reduce:transform-none motion-reduce:transition-none",
      )}
      onClick={onClick}
      type="button"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <span className="transition-transform duration-[180ms] ease-[var(--ease-standard)] group-hover:scale-[1.035] motion-reduce:transform-none motion-reduce:transition-none">
          <ConnectorLogo provider={connector.provider} size="lg" />
        </span>
        <ConnectionStatusBadge status={status} />
      </div>
      <div className="mt-4 min-w-0 pr-5">
        <p className="truncate text-sm font-semibold tracking-[-0.01em] text-[var(--text)]">{connector.name}</p>
        <p className="mt-1 line-clamp-2 text-[0.8125rem] leading-5 text-[var(--text-muted)]">{connector.description}</p>
      </div>
      <div className="mt-auto flex w-full items-end justify-between gap-3 pt-4 text-xs font-medium">
        <span className="text-[var(--text-muted)]">
          {connectionCount ? `${connectionCount} connection${connectionCount === 1 ? "" : "s"}` : connector.category}
        </span>
        <span className="inline-flex items-center gap-1 text-[var(--brand-accent)] opacity-80 transition-opacity group-hover:opacity-100">
          {status === "available" && <Plus aria-hidden="true" className="h-3.5 w-3.5" />}
          {action}
          {status !== "available" && <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5" />}
        </span>
      </div>
    </button>
  );
}
