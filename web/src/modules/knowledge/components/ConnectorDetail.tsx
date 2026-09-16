"use client";

import { ArrowLeft, ChevronRight, KeyRound, Lock, ShieldCheck } from "lucide-react";

import { StatusPill } from "@/components/patterns/StatusPill";
import { Button } from "@/components/ui/Button";
import { accountLine, connectionState } from "@/modules/knowledge/connection-state";
import type { KnowledgeConnector } from "@/modules/knowledge/connectors";
import type { Connection, ConnectorCapability } from "@/modules/knowledge/integrations-api";

import { AppIcon } from "./AppIcon";

/** The backend's capability keys, in the words an administrator uses. */
const CAPABILITY_LABELS: Record<string, string> = {
  knowledge_ingestion: "Reads documents into workspace knowledge",
  file_upload: "Accepts files uploaded here",
};

/**
 * What an account has to prove before anything is read.
 *
 * Derived from the fields the setup flow will actually ask for, so the page
 * and the form can never describe different requirements.
 */
function authenticationSummary(connector: KnowledgeConnector, capability?: ConnectorCapability) {
  // Authorizing an account is the better path wherever a deployment has it, so
  // it is what the page names — even for a connector that also takes a token.
  if (capability?.authorization_available && capability.accepts_credentials) {
    return `Sign in with ${capability.provider_display_name ?? connector.name} or use a site URL and API token`;
  }
  if (capability?.authorization_available) {
    return `Sign in with ${capability.provider_display_name ?? connector.name}`;
  }
  // The labels keep their own case: lowercasing them turns "API token" into
  // "api token", and a sentence-case rule cannot put an acronym back.
  const asked = connector.setup.credentials.map((field) => field.label);
  if (asked.length) return asked.join(" and ");
  if (capability?.authentication_type === "none") {
    return "None — nothing is fetched from another service";
  }
  if (capability?.authentication_type === "oauth") {
    return "Sign in with the provider — not configured on this deployment yet";
  }
  return "Credentials";
}

/**
 * The page a connector gets before anyone connects it.
 *
 * It answers the three questions a directory row cannot: what this reads, what
 * it will ask me for, and what it is already doing in this workspace. It is a
 * state of the Sources subview rather than a route of its own — one component
 * for every connector, so adding one never adds a page.
 */
export function ConnectorDetail({
  connector,
  available,
  capability,
  connections,
  onBack,
  onConnect,
  onOpenConnection,
}: {
  connector: KnowledgeConnector;
  /** Whether this deployment's registry has an adapter for the key. */
  available: boolean;
  /** The registry's own record. Absent in the preview, which has no registry. */
  capability?: ConnectorCapability;
  /** Accounts of this connector already authorized in this workspace. */
  connections: Connection[];
  onBack: () => void;
  onConnect: () => void;
  onOpenConnection: (id: string) => void;
}) {
  // Describing what an integration reads is a claim about behaviour, so the
  // descriptive half of the page only renders for a connector this product
  // actually implements. Everything else gets its name and an honest stop.
  const overview = available ? connector.overview : undefined;

  return (
    <section aria-label={connector.name} className="knowledge-connector-page">
      <Button
        className="-ml-2 self-start"
        icon={<ArrowLeft size={16} />}
        onClick={onBack}
        size="sm"
        variant="ghost"
      >
        Connectors
      </Button>

      <header className="knowledge-connector-page__header">
        <AppIcon className="knowledge-connector-page__mark" connector={connector.key} />
        <div className="min-w-0 flex-1">
          <h2>{connector.name}</h2>
          <p>{connector.description}</p>
        </div>
        {available ? (
          <Button onClick={onConnect}>
            {connections.length ? "Connect another account" : "Connect"}
          </Button>
        ) : (
          <StatusPill tone="neutral">Not on this deployment</StatusPill>
        )}
      </header>

      {!available && (
        <p className="knowledge-connector-page__unavailable">
          This deployment has no {connector.name} adapter, so there is nothing to connect yet.
          A platform administrator adds one by registering it in the connector registry;
          it appears here the moment they do.
        </p>
      )}

      {available && !overview && (
        <p className="knowledge-connector-page__unavailable">
          {connector.name} is registered on this deployment. Connecting it asks for the account
          it should read as, then for the content to index.
        </p>
      )}

      {overview && (
        <>
          <p className="knowledge-connector-page__summary">{overview.summary}</p>

          <div className="knowledge-connector-page__columns">
            <section aria-labelledby="connector-reads-heading">
              <div className="knowledge-section-rule">
                <h3 id="connector-reads-heading">What it reads</h3>
              </div>
              <ul className="knowledge-connector-page__list">
                {overview.reads.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>

            <section aria-labelledby="connector-access-heading">
              <div className="knowledge-section-rule">
                <h3 id="connector-access-heading">Access</h3>
              </div>
              <dl className="knowledge-kv">
                <div>
                  <dt>Sign in with</dt>
                  <dd>{authenticationSummary(connector, capability)}</dd>
                </div>
                <div><dt>Permission</dt><dd>Read-only</dd></div>
                <div>
                  <dt>Sync</dt>
                  <dd>{connector.setup.scope.length ? "On a schedule you choose" : "When a file arrives"}</dd>
                </div>
              </dl>
            </section>
          </div>

          <ul className="knowledge-connector-page__assurances">
            <li>
              <Lock aria-hidden="true" size={16} />
              Credentials are encrypted before they are stored and are never shown again.
            </li>
            <li>
              <ShieldCheck aria-hidden="true" size={16} />
              Nothing is written back — {connector.name} is only ever read from.
            </li>
            <li>
              <KeyRound aria-hidden="true" size={16} />
              Only what the connecting account can already open is read.
            </li>
          </ul>

          {capability && capability.capabilities.length > 0 && (
            <section aria-labelledby="connector-capabilities-heading">
              <div className="knowledge-section-rule">
                <h3 id="connector-capabilities-heading">Capabilities</h3>
              </div>
              <ul className="knowledge-connector-page__list">
                {capability.capabilities.map((key) => (
                  <li key={key}>{CAPABILITY_LABELS[key] ?? key.replaceAll("_", " ")}</li>
                ))}
              </ul>
            </section>
          )}

          {overview.requires && overview.requires.length > 0 && (
            <section aria-labelledby="connector-requires-heading">
              <div className="knowledge-section-rule">
                <h3 id="connector-requires-heading">Before you start</h3>
              </div>
              <ul className="knowledge-connector-page__list">
                {overview.requires.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>
          )}
        </>
      )}

      {connections.length > 0 && (
        <section aria-labelledby="connector-connections-heading">
          <div className="knowledge-section-rule">
            <h3 id="connector-connections-heading">Connected in this workspace</h3>
          </div>
          <ul className="knowledge-source-list">
            {connections.map((connection) => {
              const state = connectionState(connection);
              return (
                <li key={connection.id}>
                  <button onClick={() => onOpenConnection(connection.id)} type="button">
                    <AppIcon connector={connection.connector_key} size="sm" />
                    <span className="min-w-0 flex-1">
                      <strong className="block truncate">{connection.display_name}</strong>
                      <small className="block truncate">
                        {accountLine(connection) || "No account recorded"}
                      </small>
                    </span>
                    {state.attention && <StatusPill tone={state.tone}>{state.label}</StatusPill>}
                    <ChevronRight aria-hidden="true" size={18} />
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </section>
  );
}
