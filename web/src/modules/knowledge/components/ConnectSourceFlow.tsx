"use client";

import { CircleCheck, ExternalLink, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { Toggle } from "@/components/patterns/Toggle";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/cn";
import {
  AuthorizationCancelled,
  beginAuthorization,
  PopupBlocked,
  type PendingAuthorization,
} from "@/modules/knowledge/authorize";
import { accountLine } from "@/modules/knowledge/connection-state";
import type { ConnectorField, KnowledgeConnector } from "@/modules/knowledge/connectors";
import {
  collectionsApi,
  connectionsApi,
  scheduleFor,
  SYNC_SCHEDULES,
  type Connection,
  type ConnectorCapability,
  type SyncScheduleValue,
} from "@/modules/knowledge/integrations-api";

import { AppIcon } from "./AppIcon";
import { AuthorizationWaiting } from "./AuthorizationWaiting";
import { ResourcePicker } from "./ResourcePicker";

interface DestinationCollection {
  id: string;
  title: string;
}

type Step = "account" | "content" | "done";
type ConnectionMethod = "authorization" | "credentials";

const STEPS: { id: Step; label: string }[] = [
  { id: "account", label: "Connect account" },
  { id: "content", label: "Choose knowledge" },
  { id: "done", label: "Done" },
];

function initialValues(fields: readonly ConnectorField[]) {
  return Object.fromEntries(
    fields.map((field) => [
      field.name,
      field.defaultValue ?? (field.kind === "boolean" ? false : ""),
    ]),
  ) as Record<string, string | boolean>;
}

/** Empty optional fields are omitted rather than written as empty strings. */
function submitted(
  fields: readonly ConnectorField[],
  values: Record<string, string | boolean>,
) {
  const result: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (typeof value === "boolean") result[field.name] = value;
    else if (String(value ?? "").trim()) result[field.name] = String(value).trim();
  }
  return result;
}

/**
 * Connecting a source, in the two decisions it actually is.
 *
 * **Connect the account** proves who BoThesis may read as. **Choose knowledge**
 * decides what it reads. They are separate because they have different
 * lifetimes: an account is authorized once and then feeds any number of spaces
 * or drives, and adding the fifth one must not send anyone back through a
 * consent screen.
 *
 * A connection that already exists skips the first step entirely — which is
 * what "Add knowledge" on a connected account does.
 */
export function ConnectSourceFlow({
  connector,
  capability,
  existingConnection,
  canManageWorkspace,
  open,
  onClose,
  onConnected,
}: {
  connector: KnowledgeConnector | null;
  /** The registry's record. Decides which of the two ways to connect is offered. */
  capability?: ConnectorCapability;
  /** Set to add knowledge to an account that is already authorized. */
  existingConnection?: Connection | null;
  /** Whether this person may connect an account on the whole workspace's behalf. */
  canManageWorkspace: boolean;
  open: boolean;
  onClose: () => void;
  /** Fired once a source exists, so the list behind the dialog can refresh. */
  onConnected: () => void;
}) {
  const fieldId = useId();
  const [step, setStep] = useState<Step>("account");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);

  const [displayName, setDisplayName] = useState("");
  const [ownerType, setOwnerType] = useState<"tenant" | "user">("tenant");
  const [connectionMethod, setConnectionMethod] =
    useState<ConnectionMethod>("authorization");
  const [waiting, setWaiting] = useState(false);
  const pending = useRef<PendingAuthorization | null>(null);
  const [connectionValues, setConnectionValues] = useState<Record<string, string | boolean>>({});
  const [credentialValues, setCredentialValues] = useState<Record<string, string | boolean>>({});

  const [selected, setSelected] = useState<{ resource_type: string; external_id: string; name: string }[]>([]);
  const [manualScope, setManualScope] = useState<Record<string, string | boolean>>({});
  const [collections, setCollections] = useState<DestinationCollection[] | null>(null);
  const [targetId, setTargetId] = useState("");
  const [newCollection, setNewCollection] = useState("");
  const [schedule, setSchedule] = useState<SyncScheduleValue>("daily");
  const [createdCount, setCreatedCount] = useState(0);

  const setup = connector?.setup;
  // Authorization is offered when the deployment configured it; a credential
  // form when the connector takes one. Confluence Server has only the second,
  // Google Drive only the first, and Confluence Cloud can have both.
  const canAuthorize = capability?.authorization_available ?? false;
  const canUseCredentials =
    (capability?.accepts_credentials ?? true) && Boolean(setup?.credentials.length);
  const usesAuthorization =
    canAuthorize && (connectionMethod === "authorization" || !canUseCredentials);
  // Discovery needs an authorized account. A connector configured with a token
  // names its resource by hand, which is what its scope fields are for.
  const canDiscover = Boolean(connection?.account.id);

  const loadCollections = useCallback(async () => {
    const page = await collectionsApi.list();
    setCollections(page.items.map((item) => ({ id: item.id, title: item.title })));
  }, []);

  useEffect(() => {
    if (!open || !connector) return;
    setStep(existingConnection ? "content" : "account");
    setBusy(false);
    setWaiting(false);
    setError(null);
    setConnection(existingConnection ?? null);
    setDisplayName(connector.name);
    setConnectionMethod(canAuthorize ? "authorization" : "credentials");
    // Someone who cannot administer shared sources can still connect their own
    // account, so the flow starts where they are allowed to finish.
    setOwnerType(canManageWorkspace ? "tenant" : "user");
    setConnectionValues(initialValues(connector.setup.connection));
    setCredentialValues(initialValues(connector.setup.credentials));
    setManualScope(initialValues(connector.setup.scope));
    setSelected([]);
    setTargetId("");
    setNewCollection("");
    setSchedule("daily");
    setCollections(null);
    setCreatedCount(0);
    if (existingConnection) void loadCollections().catch(() => setCollections([]));
  }, [canAuthorize, canManageWorkspace, connector, existingConnection, loadCollections, open]);

  // A dialog that closes while consent is open would leave an orphan window.
  useEffect(() => {
    if (!open) {
      pending.current?.cancel();
      pending.current = null;
    }
  }, [open]);

  const credentialsComplete = useMemo(() => {
    if (!setup) return false;
    if (!displayName.trim()) return false;
    const missing = (fields: readonly ConnectorField[], values: Record<string, string | boolean>) =>
      fields.some((field) => field.required && !String(values[field.name] ?? "").trim());
    return !missing(setup.connection, connectionValues) && !missing(setup.credentials, credentialValues);
  }, [connectionValues, credentialValues, displayName, setup]);

  if (!open || !connector || !setup) return null;

  const afterConnected = async (value: Connection) => {
    setConnection(value);
    await loadCollections().catch(() => setCollections([]));
    setStep("content");
  };

  const authorize = async () => {
    setError(null);
    let session: PendingAuthorization;
    try {
      session = beginAuthorization({ connectorKey: connector.key, ownerType });
    } catch (cause) {
      // A blocked popup is the one failure the reader can fix themselves, and
      // it needs its own sentence rather than a generic "could not connect".
      setError(cause instanceof PopupBlocked ? cause.message : "The sign-in window could not be opened.");
      return;
    }
    pending.current = session;
    setWaiting(true);
    setBusy(true);
    try {
      const result = await session.completed;
      await afterConnected(await connectionsApi.get(result.connectionId));
    } catch (cause) {
      // Closing the window is a decision, not a failure. Saying "authorization
      // failed" for it would be telling the reader something went wrong.
      if (!(cause instanceof AuthorizationCancelled)) {
        setError(cause instanceof Error ? cause.message : "The account could not be connected.");
      }
    } finally {
      pending.current = null;
      setWaiting(false);
      setBusy(false);
    }
  };

  const cancelAuthorization = () => {
    pending.current?.cancel();
    pending.current = null;
    setWaiting(false);
    setBusy(false);
  };

  const connectWithCredentials = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await connectionsApi.createWithCredentials({
        connector_key: connector.key,
        display_name: displayName.trim(),
        config: submitted(setup.connection, connectionValues),
        credentials: submitted(setup.credentials, credentialValues),
        credential_type: connector.key,
        owner_type: ownerType === "tenant" ? "workspace" : "user",
      });
      // Verification is part of connecting: a credential that cannot reach the
      // provider should fail here, with the provider's reason, not on the first
      // sync tonight.
      await connectionsApi.validate(created.id);
      await afterConnected(await connectionsApi.get(created.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The connection could not be verified.");
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    if (!connection) return;
    setBusy(true);
    setError(null);
    try {
      const destination = targetId
        ? targetId
        : (await collectionsApi.create(newCollection.trim() || connector.name)).id;
      const plan = canDiscover
        ? selected.map((resource) => ({
            collection_id: destination,
            display_name: resource.name,
            resource_type: resource.resource_type,
            external_resource_id: resource.external_id,
            schedule: scheduleFor(schedule),
          }))
        : [
            {
              collection_id: destination,
              display_name: displayName.trim(),
              config: submitted(setup.scope, manualScope),
              schedule: scheduleFor(schedule),
            },
          ];
      // One at a time: a space that is already synchronized is rejected by name,
      // and batching would hide which of five selections was the duplicate.
      for (const source of plan) {
        await connectionsApi.createSource(connection.id, source);
      }
      setCreatedCount(plan.length);
      setStep("done");
      onConnected();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The source could not be created.");
    } finally {
      setBusy(false);
    }
  };

  const renderField = (
    field: ConnectorField,
    values: Record<string, string | boolean>,
    onChange: (next: Record<string, string | boolean>) => void,
  ) => {
    const id = `${fieldId}-${field.name}`;
    if (field.kind === "boolean") {
      return (
        <div className="knowledge-setup__switch" key={field.name}>
          <span>
            <strong>{field.label}</strong>
            {field.help && <small>{field.help}</small>}
          </span>
          <Toggle
            checked={Boolean(values[field.name])}
            label={field.label}
            onChange={(next) => onChange({ ...values, [field.name]: next })}
          />
        </div>
      );
    }
    return (
      <FormField
        helperText={field.help}
        htmlFor={id}
        key={field.name}
        label={field.label}
        required={field.required}
      >
        <Input
          autoComplete={field.kind === "secret" ? "new-password" : "off"}
          id={id}
          onChange={(event) => onChange({ ...values, [field.name]: event.target.value })}
          placeholder={field.placeholder}
          required={field.required}
          spellCheck={false}
          type={
            field.kind === "secret"
              ? "password"
              : field.kind === "email"
                ? "email"
                : field.kind === "url"
                  ? "url"
                  : "text"
          }
          value={String(values[field.name] ?? "")}
        />
      </FormField>
    );
  };

  const contentReady = canDiscover
    ? selected.length > 0 && Boolean(targetId || newCollection.trim())
    : Boolean(targetId || newCollection.trim());

  const actions = (
    <>
      {step === "account" && !waiting && (
        <>
          <Button disabled={busy} onClick={onClose} variant="ghost">
            Cancel
          </Button>
          {usesAuthorization ? (
            <Button loading={busy} onClick={() => void authorize()}>
              Continue with {capability?.provider_display_name ?? connector.name}
            </Button>
          ) : (
            <Button disabled={!credentialsComplete} loading={busy} onClick={() => void connectWithCredentials()}>
              {busy ? "Verifying…" : "Verify and continue"}
            </Button>
          )}
        </>
      )}
      {step === "content" && (
        <>
          <Button disabled={busy} onClick={onClose} variant="ghost">
            Cancel
          </Button>
          <Button disabled={!contentReady} loading={busy} onClick={() => void finish()}>
            Start syncing
          </Button>
        </>
      )}
      {step === "done" && <Button onClick={onClose}>Done</Button>}
    </>
  );

  return (
    <Dialog
      className="max-w-xl"
      footer={actions}
      onClose={onClose}
      open={open}
      title={
        step === "done"
          ? `${connector.name} connected`
          : step === "content"
            ? `Choose ${connector.name} knowledge`
            : `Connect ${connector.name}`
      }
    >
      <div className="knowledge-setup">
        <header className="knowledge-setup__identity">
          <AppIcon connector={connector.key} />
          <div>
            <strong>{connector.name}</strong>
            <small>{connector.description}</small>
          </div>
        </header>

        <ol className="knowledge-setup__steps">
          {STEPS.map((item, index) => {
            const activeIndex = STEPS.findIndex((entry) => entry.id === step);
            const state = index < activeIndex ? "done" : index === activeIndex ? "current" : "upcoming";
            return (
              <li
                className={cn("knowledge-setup__step", `knowledge-setup__step--${state}`)}
                key={item.id}
              >
                <span aria-hidden="true">
                  {state === "done" ? <CircleCheck size={14} /> : index + 1}
                </span>
                {item.label}
              </li>
            );
          })}
        </ol>

        {error && (
          <div className="knowledge-notice knowledge-notice--danger" role="alert">
            <TriangleAlert aria-hidden="true" size={16} />
            <div>
              <strong>
                {step === "account"
                  ? `${connector.name} did not accept these details`
                  : "The source could not be created"}
              </strong>
              <p>{error}</p>
            </div>
          </div>
        )}

        {step === "account" && waiting && (
          <AuthorizationWaiting
            onCancel={cancelAuthorization}
            onFocus={() => pending.current?.focus()}
            providerName={capability?.provider_display_name ?? connector.name}
          />
        )}

        {step === "account" && !waiting && (
          <div className="knowledge-setup__body">
            <div className="knowledge-setup__switch">
              <span>
                <strong>Share with the workspace</strong>
                <small>
                  {canManageWorkspace
                    ? "Everyone here can ask about this knowledge without connecting the account themselves. Turn off to keep it to your own account."
                    : "Only workspace control can connect an account for everyone. This one will be yours alone."}
                </small>
              </span>
              <Toggle
                checked={ownerType === "tenant"}
                disabled={!canManageWorkspace}
                label="Share with the workspace"
                onChange={(next) => setOwnerType(next ? "tenant" : "user")}
              />
            </div>

            {canAuthorize && canUseCredentials && (
              <fieldset className="knowledge-setup__methods">
                <legend>Authentication method</legend>
                <label>
                  <input
                    checked={connectionMethod === "authorization"}
                    name={`${fieldId}-method`}
                    onChange={() => setConnectionMethod("authorization")}
                    type="radio"
                    value="authorization"
                  />
                  <span>
                    <strong>Sign in with Atlassian</strong>
                    <small>Best for Confluence Cloud. You will choose spaces after authorizing.</small>
                  </span>
                </label>
                <label>
                  <input
                    checked={connectionMethod === "credentials"}
                    name={`${fieldId}-method`}
                    onChange={() => setConnectionMethod("credentials")}
                    type="radio"
                    value="credentials"
                  />
                  <span>
                    <strong>Use site URL and API token</strong>
                    <small>Use this for Confluence Server, Data Center, or a managed API token.</small>
                  </span>
                </label>
              </fieldset>
            )}

            {usesAuthorization ? (
              <p className="knowledge-setup__confirmed">
                You will sign in to {capability?.provider_display_name ?? connector.name} in a
                new window. {connector.name} decides what BoThesis may read, and the sign-in
                never reaches this page.
              </p>
            ) : (
              <>
                <FormField htmlFor={`${fieldId}-name`} label="Connection name" required>
                  <Input
                    id={`${fieldId}-name`}
                    onChange={(event) => setDisplayName(event.target.value)}
                    required
                    value={displayName}
                  />
                </FormField>

                {setup.connection.map((field) =>
                  renderField(field, connectionValues, setConnectionValues))}
                {canUseCredentials
                  && setup.credentials.map((field) =>
                    renderField(field, credentialValues, setCredentialValues))}

                {canUseCredentials && setup.credentialHelpUrl && (
                  <a
                    className="knowledge-setup__link"
                    href={setup.credentialHelpUrl}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <ExternalLink aria-hidden="true" size={14} />
                    Create an API token
                  </a>
                )}
              </>
            )}
          </div>
        )}

        {step === "content" && connection && (
          <div className="knowledge-setup__body">
            <p className="knowledge-setup__confirmed">
              <CircleCheck aria-hidden="true" size={16} />
              Connected as {accountLine(connection) || connection.display_name}.
            </p>

            {canDiscover ? (
              <ResourcePicker
                connectionId={connection.id}
                onChange={setSelected}
                selected={selected}
              />
            ) : (
              setup.scope.map((field) => renderField(field, manualScope, setManualScope))
            )}

            <FormField
              helperText="Where these documents land in workspace knowledge."
              htmlFor={`${fieldId}-target`}
              label="Add to collection"
              required
            >
              <Select
                id={`${fieldId}-target`}
                onChange={(event) => setTargetId(event.target.value)}
                options={[
                  { value: "", label: "New collection…" },
                  ...(collections ?? []).map((item) => ({ value: item.id, label: item.title })),
                ]}
                value={targetId}
              />
            </FormField>

            {!targetId && (
              <FormField htmlFor={`${fieldId}-new`} label="New collection name" required>
                <Input
                  id={`${fieldId}-new`}
                  onChange={(event) => setNewCollection(event.target.value)}
                  placeholder={connector.name}
                  value={newCollection}
                />
              </FormField>
            )}

            <FormField htmlFor={`${fieldId}-schedule`} label="Sync" required>
              <Select
                id={`${fieldId}-schedule`}
                onChange={(event) => setSchedule(event.target.value as SyncScheduleValue)}
                options={SYNC_SCHEDULES.map((item) => ({ value: item.value, label: item.label }))}
                value={schedule}
              />
            </FormField>
          </div>
        )}

        {step === "done" && (
          <div className="knowledge-setup__done">
            <CircleCheck aria-hidden="true" size={22} />
            <strong>
              {createdCount === 1
                ? `${connector.name} is connected`
                : `${createdCount} sources added from ${connector.name}`}
            </strong>
            <p>
              The first sync is queued. Documents appear as they are read, and the
              account&rsquo;s own page shows every run.
            </p>
          </div>
        )}
      </div>
    </Dialog>
  );
}
