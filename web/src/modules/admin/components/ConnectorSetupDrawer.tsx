"use client";

import { ChevronDown, Info } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { adminRequest } from "@/modules/admin/api";
import { errorMessage } from "@/modules/admin/format";
import type { ConnectorDefinition } from "@/modules/connectors/catalog";
import { ConnectorLogo } from "@/modules/connectors/components/ConnectorLogo";

type Row = Record<string, any>;

/**
 * Setup for one connector. Only the fields a person cannot proceed without are
 * on screen; anything the connector can infer sits behind "Advanced".
 */
export function ConnectorSetupDrawer({
  available,
  capabilityError,
  capabilityLoading,
  connections,
  connector,
  onChanged,
  onClose,
  onCreated,
}: {
  available: boolean;
  capabilityError: string | null;
  capabilityLoading: boolean;
  connections: Row[];
  connector: ConnectorDefinition;
  onChanged: () => void;
  onClose: () => void;
  onCreated: (connectionId?: string) => void;
}) {
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function requestClose() {
    if (
      dirty &&
      !window.confirm("Leave setup? What you have entered will not be saved.")
    ) {
      return;
    }
    onClose();
  }

  return (
    <Sheet
      footer={
        <div className="flex justify-end">
          <Button onClick={requestClose} variant="secondary">
            Close
          </Button>
        </div>
      }
      onClose={requestClose}
      open
      title={connector.name}
    >
      <div className="px-5 py-5 sm:px-6">
        <div className="flex items-start gap-3.5">
          <ConnectorLogo provider={connector.provider} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[1.0625rem] font-semibold tracking-[-0.015em] text-[var(--text)]">
                {connector.name}
              </h3>
              {connections.length > 0 && (
                <Badge dot tone="success">
                  {connections.length} connected
                </Badge>
              )}
            </div>
            <p className="mt-1 text-[0.8125rem] leading-5 text-[var(--text-muted)]">
              {connector.description}
            </p>
            <p className="mt-2 text-[0.75rem] text-[var(--text-muted)]">
              Signs in with {connector.authentication}. Credentials are encrypted
              before they are stored, and BoThesis only reads what the account
              you connect can already see.
            </p>
          </div>
        </div>

        {connections.length > 0 && (
          <section className="mt-6" aria-label="Existing connections">
            <h4 className="mb-2 text-[0.75rem] font-semibold uppercase tracking-[0.04em] text-[var(--text-muted)]">
              Already connected
            </h4>
            <ul className="space-y-1.5">
              {connections.map((connection) => (
                <li
                  className="flex items-center justify-between gap-3 rounded-[var(--adm-r-sm)] bg-[var(--adm-inset)] px-3 py-2 shadow-[inset_0_0_0_1px_var(--adm-hairline)]"
                  key={connection.id}
                >
                  <span className="min-w-0 truncate text-[0.8125rem] text-[var(--text)]">
                    {connection.display_name}
                  </span>
                  <Badge
                    dot
                    tone={connection.status === "active" ? "success" : "neutral"}
                  >
                    {connection.status === "active" ? "Active" : "Paused"}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section
          aria-label="Connection setup"
          className={cn(
            "mt-6",
            connections.length > 0 && "border-t border-[var(--adm-hairline)] pt-6",
          )}
        >
          <h4 className="mb-3 text-[0.75rem] font-semibold uppercase tracking-[0.04em] text-[var(--text-muted)]">
            {connections.length ? "Add another connection" : "Set up"}
          </h4>

          {capabilityLoading ? (
            <div className="space-y-3" aria-busy="true">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-32" />
            </div>
          ) : !available ? (
            <NotAvailable connector={connector} error={capabilityError} />
          ) : connector.provider === "file" ? (
            <FileSetup
              onCreated={onCreated}
              onChanged={onChanged}
              onDirtyChange={setDirty}
            />
          ) : (
            <ConfluenceSetup
              onCreated={onCreated}
              onChanged={onChanged}
              onDirtyChange={setDirty}
            />
          )}
        </section>
      </div>
    </Sheet>
  );
}

function NotAvailable({
  connector,
  error,
}: {
  connector: ConnectorDefinition;
  error: string | null;
}) {
  return (
    <div className="rounded-[var(--adm-r-md)] bg-[var(--adm-inset)] p-4 shadow-[inset_0_0_0_1px_var(--adm-hairline)]">
      <div className="flex gap-2.5">
        <Info
          aria-hidden="true"
          className="mt-px h-4 w-4 shrink-0 text-[var(--info)]"
        />
        <div className="min-w-0">
          <p className="text-[0.8125rem] font-medium text-[var(--text)]">
            {connector.name} is not switched on for this deployment
          </p>
          <p className="mt-1 text-[0.8125rem] leading-5 text-[var(--text-muted)]">
            BoThesis supports it, but the service has not been enabled here yet.
            Ask whoever runs your BoThesis deployment to turn it on.
          </p>
          {error && (
            <p className="mt-2 text-[0.75rem] leading-4 text-[var(--danger-text)]">
              Availability check failed: {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** Optional settings, hidden until someone asks for them. */
function Advanced({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-[var(--adm-r-sm)] bg-[var(--adm-inset)] shadow-[inset_0_0_0_1px_var(--adm-hairline)]">
      <button
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-[0.8125rem] font-medium text-[var(--text-secondary)]"
        onClick={() => setOpen(!open)}
        type="button"
      >
        Advanced settings
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "h-4 w-4 transition-transform duration-[var(--adm-fast)]",
            open && "rotate-180",
          )}
        />
      </button>
      {open && <div className="space-y-3.5 border-t border-[var(--adm-hairline)] p-3">{children}</div>}
    </div>
  );
}

function ConfluenceSetup({
  onChanged,
  onCreated,
  onDirtyChange,
}: {
  onChanged: () => void;
  onCreated: (connectionId?: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("Company Confluence");
  const [siteUrl, setSiteUrl] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [space, setSpace] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const formId = "confluence-setup";

  useEffect(() => {
    onDirtyChange(
      Boolean(createdId || siteUrl || email || token || space || !includeChildren),
    );
  }, [createdId, email, includeChildren, onDirtyChange, siteUrl, space, token]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const id =
        createdId ??
        String(
          (
            await adminRequest<Row>("/integration-connections", {
              method: "POST",
              body: JSON.stringify({
                connector_key: "confluence",
                display_name: name.trim(),
                config: {
                  wiki_base: siteUrl.trim(),
                  is_cloud: true,
                  space: space.trim(),
                  index_recursively: includeChildren,
                },
                credentials: {
                  confluence_username: email.trim(),
                  confluence_access_token: token,
                },
                credential_type: "api_token",
              }),
            })
          ).id,
        );
      setCreatedId(id);
      await adminRequest(`/integration-connections/${id}/validate`, {
        method: "POST",
      });
      toast({
        title: "Confluence connected",
        description: "Add it to a collection to start importing pages.",
        variant: "success",
      });
      onChanged();
      onCreated(id);
    } catch (cause) {
      const detail = errorMessage(cause);
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <form className="space-y-3.5" id={formId} onSubmit={submit}>
        {error && <ErrorState description={error} layout="inline" />}
        <FormField
          helperText="Shown in your list of connections."
          htmlFor="confluence-name"
          label="Connection name"
          required
        >
          <Input
            autoComplete="off"
            id="confluence-name"
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </FormField>
        <FormField htmlFor="confluence-url" label="Confluence address" required>
          <Input
            autoComplete="url"
            id="confluence-url"
            onChange={(event) => setSiteUrl(event.target.value)}
            placeholder="https://company.atlassian.net/wiki"
            required
            type="url"
            value={siteUrl}
          />
        </FormField>
        <FormField
          helperText="The Atlassian account BoThesis should read as. It only sees what this account can see."
          htmlFor="confluence-email"
          label="Account email"
          required
        >
          <Input
            autoComplete="username"
            id="confluence-email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="person@company.com"
            required
            type="email"
            value={email}
          />
        </FormField>
        <FormField
          helperText="Create one in Atlassian under Account settings → Security."
          htmlFor="confluence-token"
          label="API token"
          required
        >
          <Input
            autoComplete="new-password"
            id="confluence-token"
            onChange={(event) => setToken(event.target.value)}
            required
            type="password"
            value={token}
          />
        </FormField>

        <Advanced>
          <FormField
            helperText="Leave blank to import every space this account can read."
            htmlFor="confluence-space"
            label="Limit to one space"
          >
            <Input
              autoComplete="off"
              id="confluence-space"
              onChange={(event) => setSpace(event.target.value)}
              placeholder="ENG"
              value={space}
            />
          </FormField>
          <label className="flex cursor-pointer items-start gap-2.5 text-[0.8125rem] text-[var(--text-secondary)]">
            <input
              checked={includeChildren}
              className="mt-0.5 h-3.5 w-3.5 accent-[var(--brand-accent)]"
              onChange={(event) => setIncludeChildren(event.target.checked)}
              type="checkbox"
            />
            <span>
              <span className="font-medium text-[var(--text)]">
                Include child pages
              </span>
              <span className="mt-0.5 block text-[0.75rem] leading-4 text-[var(--text-muted)]">
                Keeps nested pages in scope on every sync.
              </span>
            </span>
          </label>
        </Advanced>
      </form>

      <SetupFooter created={Boolean(createdId)} form={formId} loading={submitting} />
    </>
  );
}

function FileSetup({
  onChanged,
  onCreated,
  onDirtyChange,
}: {
  onChanged: () => void;
  onCreated: (connectionId?: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("Uploaded files");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const formId = "file-setup";

  useEffect(() => {
    onDirtyChange(Boolean(createdId || name !== "Uploaded files"));
  }, [createdId, name, onDirtyChange]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const id =
        createdId ??
        String(
          (
            await adminRequest<Row>("/integration-connections", {
              method: "POST",
              body: JSON.stringify({
                connector_key: "file",
                display_name: name.trim(),
                config: {},
              }),
            })
          ).id,
        );
      setCreatedId(id);
      await adminRequest(`/integration-connections/${id}/validate`, {
        method: "POST",
      });
      toast({
        title: "File source ready",
        description: "Add it to a collection to upload into it.",
        variant: "success",
      });
      onChanged();
      onCreated(id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <form className="space-y-3.5" id={formId} onSubmit={submit}>
        {error && <ErrorState description={error} layout="inline" />}
        <FormField
          helperText="Shown in your list of connections."
          htmlFor="file-name"
          label="Connection name"
          required
        >
          <Input
            autoComplete="off"
            disabled={Boolean(createdId)}
            id="file-name"
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </FormField>
        <p className="rounded-[var(--adm-r-sm)] bg-[var(--adm-inset)] px-3 py-2.5 text-[0.8125rem] leading-5 text-[var(--text-muted)] shadow-[inset_0_0_0_1px_var(--adm-hairline)]">
          You can already upload files straight into a collection. Set this up
          only if you want uploads tracked as their own managed source.
        </p>
      </form>
      <SetupFooter created={Boolean(createdId)} form={formId} loading={submitting} />
    </>
  );
}

function SetupFooter({
  created,
  form,
  loading,
}: {
  created: boolean;
  form: string;
  loading: boolean;
}) {
  return (
    <div className="mt-5 flex items-center justify-end border-t border-[var(--adm-hairline)] pt-4">
      <Button form={form} loading={loading} type="submit">
        {created ? "Test again" : "Connect"}
      </Button>
    </div>
  );
}
