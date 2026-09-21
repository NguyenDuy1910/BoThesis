"use client";

import { useSyncExternalStore } from "react";

import { getApiConfiguration } from "@/lib/api/config";
import { apiRequest } from "@/lib/api/request";
import { apiRevision, invalidateApiData, subscribeApiData } from "@/lib/api/revision";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { retryCollectionDocument, uploadCollectionFile } from "@/modules/workspace-control/control-plane-api";
import { knowledgeApi } from "@/modules/knowledge/knowledge-api";
import {
  lastActivityLabel,
  toWorkspaceCollection,
  toWorkspaceDocument,
} from "@/modules/knowledge/view-model";
import type {
  WorkspaceKnowledgeCollection,
  WorkspaceKnowledgeDocument,
} from "@/modules/knowledge/workspace-repository";
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
 * The workspace home lists the Collections the caller may browse; each is then
 * read for the Documents inside it. They are separate loads from connections
 * and sync activity because connecting an account must refresh the sources
 * list without re-reading every document.
 */
export function useKnowledge() {
  const revision = useSyncExternalStore(subscribeApiData, apiRevision, () => 0);
  return useApiQuery<KnowledgeSnapshot>(async () => {
    const home = await knowledgeApi.home();
    const collections = home.collections;
    // Documents live inside Collections, so the workspace view is the union of
    // what each readable Collection holds.
    const pages = await Promise.all(
      collections.map((collection) =>
        knowledgeApi
          .collection(collection.id)
          .then((page) => page.documents.map((document) => toWorkspaceDocument(document, collection.title)))
          .catch(() => []),
      ),
    );
    return {
      documentCount: collections.reduce((total, collection) => total + collection.document_count, 0),
      lastSyncLabel: lastActivityLabel(collections),
      collections: collections.map(toWorkspaceCollection),
      documents: pages.flat(),
      personalCollectionId: home.personal_collection_id,
    };
  }, revision);
}

export interface KnowledgeSnapshot {
  documentCount: number;
  lastSyncLabel: string;
  collections: WorkspaceKnowledgeCollection[];
  documents: WorkspaceKnowledgeDocument[];
  personalCollectionId: string | null;
}

/**
 * Writes the Knowledge screen performs.
 *
 * Each one goes to the endpoint that owns that lifecycle and then invalidates,
 * so the list a person is looking at reflects what the server now holds rather
 * than what the click optimistically assumed.
 */
export const knowledgeActions = {
  async createCollection(title: string, description?: string) {
    const collection = await knowledgeApi.createCollection(title, description);
    invalidateApiData();
    return collection;
  },
  async upload(file: File, collectionId: string) {
    await uploadCollectionFile(collectionId, file, { idempotencyKey: crypto.randomUUID() });
    invalidateApiData();
  },
  async reindex(documentId: string) {
    await retryCollectionDocument(documentId);
    invalidateApiData();
  },
  async remove(documentId: string) {
    await apiRequest(`/documents/${documentId}`, { method: "DELETE" });
    invalidateApiData();
  },
};

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
    if (!getApiConfiguration()) {
      return knowledgeConnectors.map((connector) => ({ connector }));
    }
    const { items } = await connectionsApi.providers();
    // A response that is not the documented `{items}` shape is a broken deployment, not
    // a deployment with no connectors — and the reader gets a sentence rather
    // than whatever a property access on `undefined` happens to throw.
    if (!Array.isArray(items)) {
      throw new Error("The connector registry returned an unexpected response.");
    }
    return items.map((capability) => ({
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
    if (!getApiConfiguration()) {
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
