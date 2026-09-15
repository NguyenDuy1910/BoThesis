"use client";

import type { StatusTone } from "@/components/patterns/StatusPill";
import type {
  Connection,
  ConnectionStatus,
  Source,
  SourceStatus,
} from "@/modules/knowledge/integrations-api";
import { RECONNECT_STATUSES } from "@/modules/knowledge/integrations-api";

/**
 * How a connection's and a source's state are said out loud.
 *
 * The API's vocabulary is precise and internal: `reauth_required` is the right
 * name for a grant that no longer authenticates, and the wrong thing to show a
 * person. Each state is translated once, here, so the sources list, the detail
 * page and the activity feed cannot describe the same condition differently.
 */

export interface StateLabel {
  label: string;
  tone: StatusTone;
  /** Shown only when something is wrong. A healthy connection needs no badge. */
  attention: boolean;
}

const CONNECTION_STATES: Record<ConnectionStatus, StateLabel> = {
  draft: { label: "Not verified", tone: "neutral", attention: true },
  connected: { label: "Healthy", tone: "success", attention: false },
  expired: { label: "Access expired", tone: "danger", attention: true },
  reauth_required: { label: "Reconnect needed", tone: "danger", attention: true },
  revoked: { label: "Access revoked", tone: "danger", attention: true },
  error: { label: "Not reachable", tone: "warning", attention: true },
  disconnected: { label: "Disconnected", tone: "neutral", attention: true },
};

const SOURCE_STATES: Record<SourceStatus, StateLabel> = {
  ready: { label: "Ready", tone: "success", attention: false },
  paused: { label: "Paused", tone: "neutral", attention: true },
  failed: { label: "Last sync failed", tone: "danger", attention: true },
  connection_required: { label: "Waiting on account", tone: "danger", attention: true },
  disabled: { label: "Disabled", tone: "neutral", attention: true },
};

export function connectionState(connection: Connection): StateLabel {
  return CONNECTION_STATES[connection.status] ?? CONNECTION_STATES.error;
}

export function sourceState(source: Source): StateLabel {
  return SOURCE_STATES[source.status] ?? SOURCE_STATES.failed;
}

/** Whether only a person completing the provider's flow can fix this. */
export function needsReconnect(connection: Connection): boolean {
  return RECONNECT_STATUSES.includes(connection.status);
}

/**
 * What a connection is, in one line: the account, and the site if there is one.
 *
 * An Atlassian grant is bound to a site, so "duy@company.com · galaxyfinx"
 * distinguishes two connections that are otherwise the same account.
 */
export function accountLine(connection: Connection): string {
  const { label, resource_label: site } = connection.account;
  return [label, site].filter(Boolean).join(" · ");
}

/** Broken first, then working — the order an operator reads the list in. */
export function byAttention(left: Connection, right: Connection): number {
  const weight = (value: Connection) => (connectionState(value).attention ? 0 : 1);
  return weight(left) - weight(right) || left.display_name.localeCompare(right.display_name);
}

export function relativeTime(value: string | null): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString();
}
