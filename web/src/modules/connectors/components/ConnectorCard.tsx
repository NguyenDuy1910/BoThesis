import { ArrowRight, Plus } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

import type { ConnectorDefinition } from "../catalog";
import type { ConnectorRegistryStatus } from "../types";
import { ConnectorLogo } from "./ConnectorLogo";

const statusTone = {
  connected: { label: "Connected", tone: "success" },
  syncing: { label: "Syncing", tone: "info" },
  failed: { label: "Needs attention", tone: "danger" },
  needs_setup: { label: "Finish setup", tone: "warning" },
  disabled: { label: "Paused", tone: "neutral" },
  available: { label: "", tone: "neutral" },
  unavailable: { label: "", tone: "neutral" },
} as const;

/**
 * One connector in the catalogue. Connectors this deployment cannot actually
 * set up are dimmed and say so, rather than inviting a click that ends in a
 * dead end.
 */
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
  const unavailable = status === "unavailable";
  const badge = statusTone[status];

  return (
    <button
      aria-haspopup="dialog"
      className={cn(
        "group flex w-full flex-col items-start gap-3 rounded-[var(--adm-r-lg)] p-3.5 text-left",
        "bg-[var(--adm-surface)] shadow-[var(--adm-e1)]",
        "transition-[box-shadow,transform] duration-[var(--adm-base)] ease-[var(--adm-ease)]",
        "hover:shadow-[var(--adm-e2)] motion-safe:hover:-translate-y-px",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--adm-canvas)]",
        unavailable && "opacity-60",
      )}
      onClick={onClick}
      type="button"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <ConnectorLogo provider={connector.provider} size="md" />
        {badge.label && <Badge dot tone={badge.tone}>{badge.label}</Badge>}
      </div>

      <div className="min-w-0">
        <p className="truncate text-[0.875rem] font-semibold text-[var(--text)]">
          {connector.name}
        </p>
        <p className="mt-0.5 line-clamp-2 text-[0.75rem] leading-4 text-[var(--text-muted)]">
          {connector.description}
        </p>
      </div>

      <div className="mt-auto flex w-full items-center justify-between gap-2 pt-1 text-[0.75rem] font-medium">
        <span className="text-[var(--text-muted)]">
          {connectionCount
            ? `${connectionCount} connection${connectionCount === 1 ? "" : "s"}`
            : unavailable
              ? "Not available yet"
              : connector.authentication}
        </span>
        {!unavailable && (
          <span className="inline-flex items-center gap-1 text-[var(--brand-accent)]">
            {connectionCount ? (
              <>
                Manage
                <ArrowRight
                  aria-hidden="true"
                  className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
                />
              </>
            ) : (
              <>
                <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                Connect
              </>
            )}
          </span>
        )}
      </div>
    </button>
  );
}
