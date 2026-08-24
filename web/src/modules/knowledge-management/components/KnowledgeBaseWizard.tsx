"use client";

import {
  Check,
  ChevronRight,
  Database,
  FolderTree,
  LockKeyhole,
  RefreshCw,
  Search,
  Settings2,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";
import { adminRequest, useAdminQuery } from "@/modules/admin/api";
import { connectorDefinition } from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";
import { errorMessage, titleCase } from "@/modules/knowledge-management/presentation";
import type {
  DirectoryGroup,
  DirectoryUser,
  KnowledgeItem,
  Paginated,
  PluginBinding,
  PluginConnection,
} from "@/modules/knowledge-management/types";

const steps = [
  { label: "Source", icon: Database },
  { label: "Scope", icon: FolderTree },
  { label: "Access", icon: LockKeyhole },
  { label: "Sync", icon: RefreshCw },
  { label: "Review", icon: Search },
] as const;

type ScopeMode = "all" | "selected";
type AccessMode = "mirror" | "custom";
type SyncCadence = "manual" | "daily" | "weekly" | "custom";

interface WizardState {
  name: string;
  description: string;
  connectionId: string;
  scopeMode: ScopeMode;
  includeScopes: string;
  excludeScopes: string;
  accessMode: AccessMode;
  principals: string[];
  cadence: SyncCadence;
  cronExpression: string;
  timezone: string;
}

const initialState: WizardState = {
  name: "",
  description: "",
  connectionId: "",
  scopeMode: "all",
  includeScopes: "",
  excludeScopes: "",
  accessMode: "mirror",
  principals: [],
  cadence: "daily",
  cronExpression: "0 2 * * *",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
};

const continueLabels = ["Define scope", "Set access", "Set sync", "Review setup"];

export function KnowledgeBaseWizard({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (knowledgeBaseId: string) => void;
}) {
  const { toast } = useToast();
  const [step, setStep] = useState(0);
  const [state, setState] = useState(initialState);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [createdCollectionId, setCreatedCollectionId] = useState<string | null>(null);
  const [createdBindingId, setCreatedBindingId] = useState<string | null>(null);
  const connections = useAdminQuery<Paginated<PluginConnection>>("/plugin-connections?page_size=100&status=active");
  const users = useAdminQuery<Paginated<DirectoryUser>>("/users?page_size=100&status=active");
  const groups = useAdminQuery<Paginated<DirectoryGroup>>("/groups?page_size=100&status=active");
  const selectedConnection = connections.data?.items.find((connection) => connection.id === state.connectionId) ?? null;
  const verifiedScopes = useMemo(() => configuredScopes(selectedConnection), [selectedConnection]);
  const changed = Object.entries(state).some(([key, value]) => {
    const initial = initialState[key as keyof WizardState];
    return Array.isArray(value) ? value.length > 0 : value !== initial;
  });
  const validation = validateStep(step, state);

  function patch(values: Partial<WizardState>) {
    setState((current) => ({ ...current, ...values }));
  }

  function requestClose() {
    if (createdCollectionId) {
      onCreated(createdCollectionId);
      return;
    }
    if (changed && !window.confirm("Discard this knowledge base setup? Your selections have not been saved.")) return;
    onClose();
  }

  async function createKnowledgeBase() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const collectionId = createdCollectionId ?? (await adminRequest<KnowledgeItem>("/collections", {
        method: "POST",
        body: JSON.stringify({
          title: state.name.trim(),
          inherit_access: state.accessMode === "mirror",
          metadata: {
            description: state.description.trim() || undefined,
            access_model: state.accessMode,
          },
        }),
      })).id;
      setCreatedCollectionId(collectionId);

      if (state.accessMode === "custom") {
        await Promise.all(state.principals.map((principal) => {
          const [principalType, principalId] = principal.split(":", 2);
          return adminRequest(`/collections/${collectionId}/access`, {
            method: "PUT",
            body: JSON.stringify({
              principal_type: principalType,
              principal_id: principalId,
              role: "viewer",
            }),
          });
        }));
      }

      const bindingId = createdBindingId ?? (await adminRequest<PluginBinding>(
        `/plugin-connections/${state.connectionId}/bindings`,
        {
          method: "POST",
          body: JSON.stringify({
            target_item_id: collectionId,
            display_name: `${state.name.trim()} source`,
            config: {
              scope_mode: state.scopeMode,
              include_scopes: lines(state.includeScopes),
              exclude_scopes: lines(state.excludeScopes),
              access_model: state.accessMode,
              ...providerScopeConfig(selectedConnection, state),
            },
            schedule: schedulePayload(state),
          }),
        },
      )).id;
      setCreatedBindingId(bindingId);
      await adminRequest(`/plugin-bindings/${bindingId}/sync`, { method: "POST" });
      toast({
        title: "Knowledge base created",
        description: "The first governed sync has started.",
        variant: "success",
      });
      onCreated(collectionId);
    } catch (error) {
      const detail = errorMessage(error);
      setSubmitError(detail);
      toast({
        title: createdCollectionId ? "Setup needs attention" : "Knowledge base could not be created",
        description: detail,
        variant: "error",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet
      className="max-w-[66rem]"
      footer={(
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <p aria-live="polite" className="text-xs text-[var(--text-muted)]">
            Step {step + 1} of {steps.length}
          </p>
          <div className="flex items-center gap-2">
            <Button disabled={step === 0 || submitting} onClick={() => setStep((value) => value - 1)} variant="secondary">Back</Button>
            {step < steps.length - 1 ? (
              <Button disabled={Boolean(validation)} onClick={() => setStep((value) => value + 1)}>{continueLabels[step]}</Button>
            ) : (
              <Button loading={submitting} onClick={createKnowledgeBase}>Create and start sync</Button>
            )}
          </div>
        </div>
      )}
      onClose={requestClose}
      open
      title="New knowledge base"
    >
      <div className="knowledge-wizard">
        <nav aria-label="Knowledge base setup progress" className="knowledge-wizard__nav">
          <ol>
            {steps.map(({ label, icon: Icon }, index) => (
              <li key={label}>
                <button
                  aria-current={index === step ? "step" : undefined}
                  className={cn("knowledge-wizard__step", index === step && "is-current", index < step && "is-complete")}
                  disabled={index > step || submitting}
                  onClick={() => setStep(index)}
                  type="button"
                >
                  <span aria-hidden="true">{index < step ? <Check /> : <Icon />}</span>
                  <span>{label}</span>
                  {index === step && <ChevronRight aria-hidden="true" />}
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <div className="knowledge-wizard__content">
          <div className="knowledge-wizard__form">
            <StepHeading index={step} />
            {step === 0 && (
              <SourceStep
                connections={connections.data?.items ?? []}
                error={connections.error}
                loading={connections.loading}
                onReload={connections.reload}
                patch={patch}
                state={state}
              />
            )}
            {step === 1 && (
              <ScopeStep
                connection={selectedConnection}
                patch={patch}
                state={state}
                verifiedScopes={verifiedScopes}
              />
            )}
            {step === 2 && (
              <AccessStep
                groups={groups.data?.items ?? []}
                groupsError={groups.error}
                patch={patch}
                state={state}
                users={users.data?.items ?? []}
                usersError={users.error}
              />
            )}
            {step === 3 && <SyncStep patch={patch} state={state} />}
            {step === 4 && (
              <ReviewStep
                connection={selectedConnection}
                groups={groups.data?.items ?? []}
                state={state}
                users={users.data?.items ?? []}
              />
            )}
            {validation && <p className="mt-5 text-sm text-[var(--warning-text)]" role="status">{validation}</p>}
            {submitError && (
              <ErrorState
                className="mt-5"
                description={createdCollectionId ? `${submitError} The collection is saved, so retrying will continue this setup without creating a duplicate.` : submitError}
                title="Setup needs attention"
              />
            )}
          </div>
          <SetupSummary connection={selectedConnection} state={state} />
        </div>
      </div>
    </Sheet>
  );
}

function StepHeading({ index }: { index: number }) {
  const copy = [
    ["Choose a trusted source", "Name the knowledge base and select one validated connection."],
    ["Set the content boundary", "Include only the source locations this knowledge base is allowed to index."],
    ["Define who can use it", "Mirror source permissions or grant a controlled audience explicit viewer access."],
    ["Choose the refresh policy", "Schedule incremental syncs; overlapping runs are skipped by default."],
    ["Review the governed setup", "Confirm source, scope, access, and schedule before the first sync starts."],
  ];
  return (
    <header className="mb-6">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--brand-accent)]">{steps[index].label}</p>
      <h3 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-[var(--text)]">{copy[index][0]}</h3>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--text-muted)]">{copy[index][1]}</p>
    </header>
  );
}

function SourceStep({
  connections,
  error,
  loading,
  onReload,
  patch,
  state,
}: {
  connections: PluginConnection[];
  error: string | null;
  loading: boolean;
  onReload: () => void;
  patch: (values: Partial<WizardState>) => void;
  state: WizardState;
}) {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField htmlFor="knowledge-base-name" label="Knowledge base name" required>
          <Input autoComplete="off" id="knowledge-base-name" maxLength={255} name="knowledge_base_name" onChange={(event) => patch({ name: event.target.value })} placeholder="Engineering handbook…" required value={state.name} />
        </FormField>
        <FormField htmlFor="knowledge-base-description" label="Purpose" helperText="Shown to admins reviewing access and readiness.">
          <Input autoComplete="off" id="knowledge-base-description" maxLength={500} name="knowledge_base_description" onChange={(event) => patch({ description: event.target.value })} placeholder="Product and engineering operating knowledge…" value={state.description} />
        </FormField>
      </div>
      {loading ? <p className="text-sm text-[var(--text-muted)]">Loading validated connections…</p> : error ? (
        <ErrorState actionLabel="Retry" description={error} onAction={onReload} title="Sources are unavailable" />
      ) : connections.length ? (
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-[var(--text-secondary)]">Validated connection</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {connections.map((connection) => {
              const definition = connectorDefinition(connection.plugin_key);
              return (
                <label className={cn("knowledge-choice", state.connectionId === connection.id && "is-selected")} key={connection.id}>
                  <input checked={state.connectionId === connection.id} name="connection" onChange={() => patch({ connectionId: connection.id })} type="radio" value={connection.id} />
                  <ConnectorLogo provider={connection.plugin_key} size="sm" />
                  <span className="min-w-0 flex-1">
                    <strong>{connection.display_name}</strong>
                    <small>{definition?.name ?? titleCase(connection.plugin_key)} · {connection.owner_type} connection</small>
                  </span>
                  <Badge dot variant="success">Validated</Badge>
                </label>
              );
            })}
          </div>
        </fieldset>
      ) : (
        <EmptyState
          icon={<Database className="h-5 w-5" />}
          size="md"
          title="No validated sources"
          description="Validate a connection in Sources & Integrations before creating a knowledge base."
        />
      )}
    </div>
  );
}

function ScopeStep({
  connection,
  patch,
  state,
  verifiedScopes,
}: {
  connection: PluginConnection | null;
  patch: (values: Partial<WizardState>) => void;
  state: WizardState;
  verifiedScopes: string[];
}) {
  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-sm font-medium text-[var(--text-secondary)]">Selection mode</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          <ChoiceCard checked={state.scopeMode === "all"} description="Use every location available to this validated connection." label="All connected content" name="scope-mode" onChange={() => patch({ scopeMode: "all" })} />
          <ChoiceCard checked={state.scopeMode === "selected"} description="Limit ingestion to exact provider scope identifiers." label="Selected locations" name="scope-mode" onChange={() => patch({ scopeMode: "selected" })} />
        </div>
      </fieldset>
      {state.scopeMode === "selected" && (
        <div className="knowledge-scope-tree">
          <div className="knowledge-scope-tree__heading">
            <span><FolderTree aria-hidden="true" /> Connected hierarchy</span>
            <small>Only persisted connection scope is shown—no inferred content.</small>
          </div>
          <div className="knowledge-scope-tree__root">
            <ConnectorLogo provider={connection?.plugin_key ?? "file"} size="sm" />
            <span><strong>{connection?.display_name ?? "Selected connection"}</strong><small>Connection root</small></span>
          </div>
          {verifiedScopes.length ? (
            <ul>
              {verifiedScopes.map((scope) => (
                <li key={scope}>
                  <label>
                    <input
                      checked={lines(state.includeScopes).includes(scope)}
                      onChange={() => patch({ includeScopes: toggleLine(state.includeScopes, scope) })}
                      type="checkbox"
                    />
                    <span>{scope}</span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p className="knowledge-scope-tree__empty">This connection has no persisted scope hierarchy. Add exact provider IDs below; they remain visible in the binding audit record.</p>
          )}
          <div className="grid gap-4 border-t border-[var(--border)] p-4 sm:grid-cols-2">
            <FormField htmlFor="include-scopes" label="Include scope IDs" helperText="One exact space, project, folder, or path ID per line." required>
              <textarea autoComplete="off" className={ui.textarea} id="include-scopes" name="include_scopes" onChange={(event) => patch({ includeScopes: event.target.value })} placeholder="ENG&#10;PRODUCT/roadmaps…" required rows={5} value={state.includeScopes} />
            </FormField>
            <FormField htmlFor="exclude-scopes" label="Exclude scope IDs" helperText="Exclusions override included parent locations.">
              <textarea autoComplete="off" className={ui.textarea} id="exclude-scopes" name="exclude_scopes" onChange={(event) => patch({ excludeScopes: event.target.value })} placeholder="ENG/private&#10;PRODUCT/archive…" rows={5} value={state.excludeScopes} />
            </FormField>
          </div>
        </div>
      )}
    </div>
  );
}

function AccessStep({
  groups,
  groupsError,
  patch,
  state,
  users,
  usersError,
}: {
  groups: DirectoryGroup[];
  groupsError: string | null;
  patch: (values: Partial<WizardState>) => void;
  state: WizardState;
  users: DirectoryUser[];
  usersError: string | null;
}) {
  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-sm font-medium text-[var(--text-secondary)]">Access model</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          <ChoiceCard checked={state.accessMode === "mirror"} description="Keep the collection inheritable and preserve provider permission lineage." label="Mirror source access" name="access-mode" onChange={() => patch({ accessMode: "mirror", principals: [] })} />
          <ChoiceCard checked={state.accessMode === "custom"} description="Grant explicit viewer access to selected tenant users and groups." label="Custom audience" name="access-mode" onChange={() => patch({ accessMode: "custom" })} />
        </div>
      </fieldset>
      {state.accessMode === "mirror" ? (
        <div className="knowledge-callout">
          <LockKeyhole aria-hidden="true" />
          <span><strong>Source permissions remain authoritative.</strong><small>You become the collection owner. Other users still need collection access, and provider document ACLs are enforced before content reaches the agent.</small></span>
        </div>
      ) : usersError || groupsError ? (
        <ErrorState description={usersError ?? groupsError ?? "The directory is unavailable."} title="Audience directory unavailable" />
      ) : (
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-[var(--text-secondary)]">Viewer audience</legend>
          <div className="knowledge-directory">
            <DirectorySection icon={<Users />} label="People" values={users.map((user) => ({ id: `user:${user.id}`, primary: user.display_name ?? user.email, secondary: user.email }))} selected={state.principals} onToggle={(id) => patch({ principals: toggleValue(state.principals, id) })} />
            <DirectorySection icon={<Settings2 />} label="Groups" values={groups.map((group) => ({ id: `group:${group.id}`, primary: group.display_name, secondary: `${group.member_count} members` }))} selected={state.principals} onToggle={(id) => patch({ principals: toggleValue(state.principals, id) })} />
          </div>
        </fieldset>
      )}
    </div>
  );
}

function SyncStep({ patch, state }: { patch: (values: Partial<WizardState>) => void; state: WizardState }) {
  return (
    <div className="space-y-5">
      <FormField htmlFor="sync-cadence" label="Refresh cadence" helperText="The initial sync starts immediately after creation.">
        <Select
          id="sync-cadence"
          name="sync_cadence"
          onChange={(event) => {
            const cadence = event.target.value as SyncCadence;
            patch({ cadence, cronExpression: cadence === "daily" ? "0 2 * * *" : cadence === "weekly" ? "0 2 * * 1" : state.cronExpression });
          }}
          options={[
            { value: "manual", label: "Manual only" },
            { value: "daily", label: "Daily at 02:00" },
            { value: "weekly", label: "Weekly on Monday at 02:00" },
            { value: "custom", label: "Custom cron schedule" },
          ]}
          value={state.cadence}
        />
      </FormField>
      {state.cadence !== "manual" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField htmlFor="sync-cron" label="Cron expression" helperText="Stored with the binding scheduler." required>
            <Input autoComplete="off" disabled={state.cadence !== "custom"} id="sync-cron" name="sync_cron" onChange={(event) => patch({ cronExpression: event.target.value })} required value={state.cronExpression} />
          </FormField>
          <FormField htmlFor="sync-timezone" label="Timezone" required>
            <Input autoComplete="off" id="sync-timezone" name="sync_timezone" onChange={(event) => patch({ timezone: event.target.value })} required value={state.timezone} />
          </FormField>
        </div>
      )}
      <div className="knowledge-callout">
        <RefreshCw aria-hidden="true" />
        <span><strong>Incremental and collision-safe.</strong><small>Existing checkpoints are retained, and overlapping runs use the platform’s skip policy.</small></span>
      </div>
    </div>
  );
}

function ReviewStep({ connection, groups, state, users }: { connection: PluginConnection | null; groups: DirectoryGroup[]; state: WizardState; users: DirectoryUser[] }) {
  const principalLabels = state.principals.map((value) => {
    const [type, id] = value.split(":", 2);
    return type === "user"
      ? users.find((user) => user.id === id)?.display_name ?? users.find((user) => user.id === id)?.email ?? id
      : groups.find((group) => group.id === id)?.display_name ?? id;
  });
  return (
    <dl className="knowledge-review">
      <ReviewRow label="Knowledge base" value={state.name} />
      <ReviewRow label="Source" value={connection?.display_name ?? "Not selected"} />
      <ReviewRow label="Scope" value={state.scopeMode === "all" ? "All connected content" : `${lines(state.includeScopes).length} included · ${lines(state.excludeScopes).length} excluded`} />
      <ReviewRow label="Access" value={state.accessMode === "mirror" ? "Creator owns collection · provider document ACLs apply" : `Creator owns collection · ${principalLabels.join(", ") || "no additional viewers"}`} />
      <ReviewRow label="Sync" value={state.cadence === "manual" ? "Manual after initial sync" : `${titleCase(state.cadence)} · ${state.cronExpression} · ${state.timezone}`} />
      <ReviewRow label="After create" value="Create collection → store access grants → bind source → start initial sync" />
    </dl>
  );
}

function SetupSummary({ connection, state }: { connection: PluginConnection | null; state: WizardState }) {
  return (
    <aside aria-label="Setup summary" className="knowledge-wizard__summary">
      <p>Live summary</p>
      <div className="knowledge-wizard__summary-source">
        <ConnectorLogo provider={connection?.plugin_key ?? "file"} size="sm" />
        <span><strong>{state.name || "Untitled knowledge base"}</strong><small>{connection?.display_name ?? "No source selected"}</small></span>
      </div>
      <dl>
        <ReviewRow label="Scope" value={state.scopeMode === "all" ? "All content" : `${lines(state.includeScopes).length} included`} />
        <ReviewRow label="Access" value={state.accessMode === "mirror" ? "Source permissions" : `${state.principals.length} principals`} />
        <ReviewRow label="Refresh" value={titleCase(state.cadence)} />
      </dl>
      <div className="knowledge-wizard__assurance">
        <LockKeyhole aria-hidden="true" />
        Tenant, lineage, access, and audit boundaries stay server enforced.
      </div>
    </aside>
  );
}

function ChoiceCard({ checked, description, label, name, onChange }: { checked: boolean; description: string; label: string; name: string; onChange: () => void }) {
  return (
    <label className={cn("knowledge-choice", checked && "is-selected")}>
      <input checked={checked} name={name} onChange={onChange} type="radio" />
      <span className="min-w-0"><strong>{label}</strong><small>{description}</small></span>
    </label>
  );
}

function DirectorySection({ icon, label, onToggle, selected, values }: { icon: React.ReactNode; label: string; onToggle: (id: string) => void; selected: string[]; values: Array<{ id: string; primary: string; secondary: string }> }) {
  return (
    <section>
      <h4>{icon}{label}<span>{values.length}</span></h4>
      {values.length ? values.map((value) => (
        <label key={value.id}>
          <input checked={selected.includes(value.id)} onChange={() => onToggle(value.id)} type="checkbox" />
          <span><strong>{value.primary}</strong><small>{value.secondary}</small></span>
        </label>
      )) : <p>No active {label.toLowerCase()} available.</p>}
    </section>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function validateStep(step: number, state: WizardState) {
  if (step === 0 && !state.name.trim()) return "Enter a knowledge base name to continue.";
  if (step === 0 && !state.connectionId) return "Select a validated connection to continue.";
  if (step === 1 && state.scopeMode === "selected" && !lines(state.includeScopes).length) return "Add at least one included scope identifier.";
  if (step === 2 && state.accessMode === "custom" && !state.principals.length) return "Select at least one user or group for custom access.";
  if (step === 3 && state.cadence !== "manual" && !state.cronExpression.trim()) return "Enter a cron expression for the sync schedule.";
  return null;
}

function schedulePayload(state: WizardState) {
  if (state.cadence === "manual") return null;
  return {
    schedule_type: "cron",
    cron_expression: state.cronExpression.trim(),
    timezone: state.timezone.trim(),
    enabled: true,
    overlap_policy: "skip",
  };
}

function lines(value: string) {
  return Array.from(new Set(value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean)));
}

function toggleLine(value: string, target: string) {
  const current = lines(value);
  return (current.includes(target) ? current.filter((item) => item !== target) : [...current, target]).join("\n");
}

function toggleValue(values: string[], target: string) {
  return values.includes(target) ? values.filter((value) => value !== target) : [...values, target];
}

function configuredScopes(connection: PluginConnection | null) {
  if (!connection) return [];
  const config = connection.config;
  const candidates = [config.space, config.space_key, config.space_keys, config.scopes, config.folder_ids, config.project_keys];
  return Array.from(new Set(candidates.flatMap((candidate) => {
    if (Array.isArray(candidate)) return candidate.map(String);
    return typeof candidate === "string" ? lines(candidate) : [];
  })));
}

function providerScopeConfig(connection: PluginConnection | null, state: WizardState) {
  if (!connection || state.scopeMode === "all") return {};
  const included = lines(state.includeScopes);
  if (connection.plugin_key === "confluence") return { space: included.join(",") };
  return {};
}
