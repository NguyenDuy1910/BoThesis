"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import type { Paginated } from "@/modules/admin/collections";
import { errorMessage } from "@/modules/admin/format";

type AccessTab = "people" | "groups" | "roles" | "requests" | "policies";

type Row = Record<string, any>;

const FORM_ID = "access-create-form";

const copy: Record<
  Exclude<AccessTab, "requests">,
  { title: string; intro: string; submit: string }
> = {
  people: {
    title: "Invite a person",
    intro:
      "They join this workspace with the role you choose. You can change it later.",
    submit: "Send invite",
  },
  groups: {
    title: "Create a group",
    intro:
      "Grant a whole team access to a collection at once instead of person by person.",
    submit: "Create group",
  },
  roles: {
    title: "Create a role",
    intro: "A role decides what someone can do inside the Admin console.",
    submit: "Create role",
  },
  policies: {
    title: "Create an access policy",
    intro:
      "A policy pins exactly who may and may not read one collection, overriding inherited access.",
    submit: "Create policy",
  },
};

function splitList(value: string) {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

/**
 * One dialog for the four things you can create under Access. The fields
 * differ; the layout, validation and error handling do not.
 */
export function AccessCreateDialog({
  onClose,
  onCreated,
  tab,
}: {
  onClose: () => void;
  onCreated: () => void;
  tab: AccessTab;
}) {
  const { toast } = useToast();
  const [roles, setRoles] = useState<Row[]>([]);
  const [collections, setCollections] = useState<Row[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      if (tab === "people") {
        const result = await adminRequest<Paginated<Row>>(
          "/roles?page_size=100&status=active",
          { signal: controller.signal },
        );
        setRoles(result.items ?? []);
      }
      if (tab === "policies") {
        const result = await adminRequest<Paginated<Row>>(
          "/items?item_type=collection&page_size=100",
          { signal: controller.signal },
        );
        setCollections(result.items ?? []);
      }
    };
    load().catch(() => undefined);
    return () => controller.abort();
  }, [tab]);

  if (tab === "requests") return null;
  const text = copy[tab];

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();

    let endpoint = "";
    let payload: Row = {};
    if (tab === "people") {
      endpoint = "/users";
      payload = {
        email: value("email"),
        display_name: value("display_name"),
        role_id: value("role_id"),
        group_ids: [],
      };
    } else if (tab === "groups") {
      endpoint = "/groups";
      payload = {
        code: value("code"),
        display_name: value("display_name"),
        description: value("description") || undefined,
        permission_codes: [],
      };
    } else if (tab === "roles") {
      endpoint = "/roles";
      payload = {
        code: value("code"),
        display_name: value("display_name"),
        permission_codes: splitList(value("permission_codes")),
      };
    } else {
      endpoint = "/acl-policies";
      payload = {
        name: value("name"),
        resource_type: "item",
        resource_id: value("resource_id"),
        allowed_principal_tokens: splitList(value("allowed_principal_tokens")),
        denied_principal_tokens: splitList(value("denied_principal_tokens")),
      };
    }

    setSaving(true);
    setError(null);
    try {
      await adminRequest(endpoint, { method: "POST", body: JSON.stringify(payload) });
      toast({ title: `${text.title.replace(/^(Create|Invite) an? /i, "")} created`, variant: "success" });
      onCreated();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      className="max-w-lg"
      footer={
        <>
          <Button disabled={saving} onClick={onClose} variant="secondary">
            Cancel
          </Button>
          <Button form={FORM_ID} loading={saving} type="submit">
            {text.submit}
          </Button>
        </>
      }
      onClose={() => {
        if (!saving) onClose();
      }}
      open
      title={text.title}
    >
      <form className="space-y-4" id={FORM_ID} onSubmit={submit}>
        <p className="text-[0.8125rem] leading-5 text-[var(--text-tertiary)]">
          {text.intro}
        </p>
        {error && <ErrorState description={error} layout="inline" />}

        {tab === "people" && (
          <>
            <FormField htmlFor="invite-email" label="Work email" required>
              <Input
                autoComplete="off"
                id="invite-email"
                name="email"
                placeholder="name@company.com"
                required
                type="email"
              />
            </FormField>
            <FormField htmlFor="invite-name" label="Full name" required>
              <Input
                autoComplete="off"
                id="invite-name"
                name="display_name"
                placeholder="Alex Chen"
                required
              />
            </FormField>
            <FormField
              helperText="Decides what they can manage in this console."
              htmlFor="invite-role"
              label="Role"
              required
            >
              <Select
                id="invite-role"
                name="role_id"
                options={roles.map((role) => ({
                  value: role.id,
                  label: role.display_name,
                }))}
                placeholder="Choose a role"
                required
              />
            </FormField>
          </>
        )}

        {tab === "groups" && (
          <>
            <FormField htmlFor="group-name" label="Group name" required>
              <Input
                autoComplete="off"
                id="group-name"
                name="display_name"
                placeholder="Customer Support"
                required
              />
            </FormField>
            <FormField
              helperText="A short identifier used when granting access. Lowercase, no spaces."
              htmlFor="group-code"
              label="Reference"
              required
            >
              <Input
                autoComplete="off"
                id="group-code"
                name="code"
                placeholder="customer-support"
                required
              />
            </FormField>
            <FormField htmlFor="group-description" label="Description">
              <Textarea
                id="group-description"
                name="description"
                placeholder="Who belongs in this group and why."
                rows={2}
              />
            </FormField>
          </>
        )}

        {tab === "roles" && (
          <>
            <FormField htmlFor="role-name" label="Role name" required>
              <Input
                autoComplete="off"
                id="role-name"
                name="display_name"
                placeholder="Knowledge manager"
                required
              />
            </FormField>
            <FormField
              helperText="A short identifier. Lowercase, no spaces."
              htmlFor="role-code"
              label="Reference"
              required
            >
              <Input
                autoComplete="off"
                id="role-code"
                name="code"
                placeholder="knowledge-manager"
                required
              />
            </FormField>
            <FormField
              helperText="Separate with commas, for example: knowledge.read, source.manage"
              htmlFor="role-permissions"
              label="Permissions"
              required
            >
              <Input
                autoComplete="off"
                id="role-permissions"
                name="permission_codes"
                placeholder="knowledge.read, source.manage"
                required
              />
            </FormField>
          </>
        )}

        {tab === "policies" && (
          <>
            <FormField htmlFor="policy-name" label="Policy name" required>
              <Input
                autoComplete="off"
                id="policy-name"
                name="name"
                placeholder="Finance handbook — leadership only"
                required
              />
            </FormField>
            <FormField htmlFor="policy-collection" label="Applies to" required>
              <Select
                id="policy-collection"
                name="resource_id"
                options={collections.map((collection) => ({
                  value: collection.id,
                  label: collection.title,
                }))}
                placeholder="Choose a collection"
                required
              />
            </FormField>
            <FormField
              helperText="Separate with commas, for example: group:finance, email:alex@company.com"
              htmlFor="policy-allowed"
              label="Allow"
              required
            >
              <Input
                autoComplete="off"
                id="policy-allowed"
                name="allowed_principal_tokens"
                placeholder="group:finance"
                required
              />
            </FormField>
            <FormField
              helperText="Denials always win, even when someone is allowed elsewhere."
              htmlFor="policy-denied"
              label="Deny"
            >
              <Input
                autoComplete="off"
                id="policy-denied"
                name="denied_principal_tokens"
                placeholder="group:contractors"
              />
            </FormField>
          </>
        )}
      </form>
    </Dialog>
  );
}
