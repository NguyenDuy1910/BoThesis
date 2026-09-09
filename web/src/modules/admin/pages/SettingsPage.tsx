"use client";

import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { appBrand } from "@/lib/brand";
import { adminRequest } from "@/modules/admin/api";
import { formatDateTime } from "@/modules/admin/format";
import { errorMessage } from "@/modules/admin/format";
import { useAdminWorkspace } from "@/modules/admin/workspace";
import { useTheme, type ThemeMode } from "@/modules/chat/hooks/useTheme";

const themeChoices: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match system", icon: Monitor },
];

export function SettingsPage() {
  const { tenant, loading, error, reload } = useAdminWorkspace();
  const [renaming, setRenaming] = useState(false);

  if (error) {
    return (
      <ErrorState
        actionLabel="Try again"
        description={error}
        onAction={reload}
        title="Settings could not be loaded"
      />
    );
  }

  return (
    <>
      <PageHeader
        description="How this workspace identifies itself, and how the console looks to you."
        title="Settings"
      />

      <div className="grid gap-4">
        <Card>
          <CardHeader
            actions={
              tenant && (
                <Button onClick={() => setRenaming(true)} size="sm" variant="secondary">
                  Rename workspace
                </Button>
              )
            }
            description={`The name your team sees across ${appBrand.productName}.`}
            title="Workspace"
          />
          <CardBody>
            {loading || !tenant ? (
              <div className="grid gap-4 sm:grid-cols-3">
                {[0, 1, 2].map((index) => (
                  <div className="space-y-2" key={index}>
                    <Skeleton className="h-2.5 w-20" />
                    <Skeleton className="h-4 w-32" />
                  </div>
                ))}
              </div>
            ) : (
              <dl className="grid gap-4 sm:grid-cols-3">
                <Detail label="Name">{tenant.name}</Detail>
                <Detail label="Status">
                  <StatusBadge status={tenant.status} />
                </Detail>
                <Detail label="Last changed">
                  {formatDateTime(tenant.updated_at)}
                </Detail>
              </dl>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            description="Applies to this browser only. Everyone else keeps their own choice."
            title="Appearance"
          />
          <CardBody>
            <ThemePicker />
          </CardBody>
        </Card>
      </div>

      {renaming && tenant && (
        <RenameWorkspaceDialog
          currentName={tenant.name}
          onClose={() => setRenaming(false)}
          onSaved={() => {
            setRenaming(false);
            reload();
          }}
          tenantId={tenant.id}
        />
      )}
    </>
  );
}

function Detail({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div>
      <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-muted)]">
        {label}
      </dt>
      <dd className="mt-1 text-[0.875rem] text-[var(--text)]">{children}</dd>
    </div>
  );
}

function ThemePicker() {
  const { theme, setTheme } = useTheme();
  return (
    <div
      aria-label="Colour theme"
      className="grid gap-2 sm:grid-cols-3"
      role="radiogroup"
    >
      {themeChoices.map((choice) => {
        const Icon = choice.icon;
        const active = theme === choice.value;
        return (
          <button
            aria-checked={active}
            className={cn(
              "flex items-center gap-2.5 rounded-[var(--adm-r-md)] px-3 py-2.5 text-left transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
              active
                ? "bg-[var(--surface-selected)] text-[var(--brand-accent)] shadow-[inset_0_0_0_1px_var(--brand-accent)]"
                : "text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--adm-hairline-strong)] hover:bg-[var(--adm-inset)]",
            )}
            key={choice.value}
            onClick={() => setTheme(choice.value)}
            role="radio"
            type="button"
          >
            <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span className="flex-1 text-[0.8125rem] font-medium">{choice.label}</span>
            {active && <Check aria-hidden="true" className="h-3.5 w-3.5" />}
          </button>
        );
      })}
    </div>
  );
}

function RenameWorkspaceDialog({
  currentName,
  onClose,
  onSaved,
  tenantId,
}: {
  currentName: string;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
}) {
  const { toast } = useToast();
  const nameRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState(currentName);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = name.trim();

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !trimmed) return;
    setSaving(true);
    setError(null);
    try {
      await adminRequest(`/spaces/${tenantId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: trimmed }),
      });
      toast({ title: "Workspace renamed", variant: "success" });
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause, "The workspace could not be renamed."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      className="max-w-md"
      footer={
        <>
          <Button disabled={saving} onClick={onClose} variant="secondary">
            Cancel
          </Button>
          <Button
            disabled={!trimmed || trimmed === currentName}
            form="workspace-rename-form"
            loading={saving}
            type="submit"
          >
            Save changes
          </Button>
        </>
      }
      initialFocusRef={nameRef}
      onClose={() => {
        if (!saving) onClose();
      }}
      open
      title="Rename workspace"
    >
      <form className="space-y-4" id="workspace-rename-form" onSubmit={save}>
        {error && <ErrorState description={error} layout="inline" />}
        <FormField htmlFor="workspace-name" label="Workspace name" required>
          <Input
            autoComplete="off"
            id="workspace-name"
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
            ref={nameRef}
            value={name}
          />
        </FormField>
      </form>
    </Dialog>
  );
}
