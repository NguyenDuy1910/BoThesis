"use client";

import { useSyncExternalStore } from "react";

import { getLiveApiConfiguration } from "@/lib/api/config";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { mockApi } from "@/mocks/bothesis-api.mock";
import {
  describeConnector,
  knowledgeConnectors,
  type KnowledgeConnector,
} from "@/modules/knowledge/connectors";
import {
  connectionsApi,
  sourcesApi,
  type Connection,
  type ConnectorCapability,
  type Source,
  type SourceRun,
} from "@/modules/knowledge/integrations-api";

/**
 * Everything the Knowledge shell reads.
 *
 * Documents still come from the preview data layer; connections, sources and
 * sync activity come from the API whenever a real session is present. They are
 * separate loads because they answer to separate things — connecting an
 * account must refresh the sources list without re-reading every document.
 */
export function useKnowledge() {
  const revision = useSyncExternalStore(mockApi.subscribe, mockApi.revision, () => 0);
  return useApiQuery(async () => {
    const [overview, documents] = await Promise.all([
      mockApi.knowledge.overview(),
      mockApi.knowledge.documents(),
    ]);
    return { ...overview, documents };
  }, revision);
}

export const knowledgeActions = mockApi.knowledge;

/**
 * What this deployment can actually connect.
 *
 * The catalogue in `connectors.ts` only describes; the backend's registry
 * decides. Each entry carries the registry's own record beside the
 * description, because whether a connector is authorized by OAuth, takes an
 * API token, or is unavailable here are all facts about this deployment.
 */
export interface ConnectorEntry {
  connector: KnowledgeConnector;
  capability?: ConnectorCapability;
}

export function useConnectorCatalogue() {
  return useApiQuery<ConnectorEntry[]>(async () => {
    if (!getLiveApiConfiguration()) {
      return knowledgeConnectors.map((connector) => ({ connector }));
    }
    const { connectors } = await connectionsApi.providers();
    // A response that is not the documented shape is a broken deployment, not
    // a deployment with no connectors — and the reader gets a sentence rather
    // than whatever a property access on `undefined` happens to throw.
    if (!Array.isArray(connectors)) {
      throw new Error("The connector registry returned an unexpected response.");
    }
    return connectors.map((capability) => ({
      connector: describeConnector(capability.connector_key, capability.display_name),
      capability,
    }));
  });
}

export interface ConnectionsSnapshot {
  connections: Connection[];
  sources: Source[];
  runs: SourceRun[];
  /** False in the design preview, where there is no registry to connect against. */
  live: boolean;
}

/**
 * Connected accounts, what they synchronize, and how those runs went.
 *
 * One load, because the three are read together everywhere: a source is shown
 * with the account behind it, and an account is shown with how much depends on
 * it. Sync activity is best-effort — Temporal being down should not empty the
 * list of connections.
 */
export function useConnections() {
  return useApiQuery<ConnectionsSnapshot>(async () => {
    if (!getLiveApiConfiguration()) {
      return { connections: [], sources: [], runs: [], live: false };
    }
    const [connections, sources] = await Promise.all([
      connectionsApi.list(),
      sourcesApi.list(),
    ]);
    const runs = await sourcesApi.allRuns().catch(() => ({ items: [] as SourceRun[] }));
    return {
      connections: connections.items,
      sources: sources.items,
      runs: runs.items,
      live: true,
    };
  });
}
