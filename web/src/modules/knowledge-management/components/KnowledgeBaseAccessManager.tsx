"use client";

import { ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { FormField } from "@/components/ui/FormField";
import { Select } from "@/components/ui/Select";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import { errorMessage, titleCase } from "@/modules/knowledge-management/presentation";
import type {
  CollectionGrant,
  DirectoryGroup,
  DirectoryUser,
} from "@/modules/knowledge-management/types";

export function KnowledgeBaseAccessManager({
  grants,
  groups,
  inheritAccess,
  knowledgeBaseId,
  onChanged,
  users,
}: {
  grants: CollectionGrant[];
  groups: DirectoryGroup[];
  inheritAccess: boolean;
  knowledgeBaseId: string;
  onChanged: () => void;
  users: DirectoryUser[];
}) {
  const { toast } = useToast();
  const [principalType, setPrincipalType] = useState<"user" | "group">("user");
  const [principalId, setPrincipalId] = useState("");
  const [role, setRole] = useState<"editor" | "viewer">("viewer");
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const availablePrincipals = useMemo(() => {
    const values = principalType === "user"
      ? users.filter((user) => user.status === "active").map((user) => ({
          value: user.id,
          label: user.display_name || user.email,
        }))
      : groups.filter((group) => group.status === "active").map((group) => ({
          value: group.id,
          label: group.display_name,
        }));
    return [{ value: "", label: `Choose a ${principalType}` }, ...values];
  }, [groups, principalType, users]);

  async function grantAccess(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!principalId || action) return;
    setAction("grant");
    setError(null);
    try {
      await adminRequest(`/collections/${knowledgeBaseId}/access`, {
        method: "PUT",
        body: JSON.stringify({
          principal_type: principalType,
          principal_id: principalId,
          role,
        }),
      });
      toast({ title: "Access updated", variant: "success" });
      setPrincipalId("");
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setAction(null);
    }
  }

  async function revoke(grant: CollectionGrant) {
    const key = `${grant.principal_type}:${grant.principal_id}`;
    setAction(key);
    setError(null);
    try {
      await adminRequest(
        `/collections/${knowledgeBaseId}/access/${grant.principal_type}/${grant.principal_id}`,
        { method: "DELETE" },
      );
      toast({ title: "Access removed", variant: "success" });
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setAction(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text)]" id="access">People &amp; access</h2>
          <p className="mt-0.5 text-xs leading-5 text-[var(--text-muted)]">
            {inheritAccess
              ? "Collection access and source permissions are both enforced before retrieval."
              : "Only explicit collection grants are used for this knowledge base."}
          </p>
        </div>
        <Badge variant={inheritAccess ? "primary" : "default"}>
          {inheritAccess ? "Inherited access on" : "Explicit access"}
        </Badge>
      </CardHeader>
      <CardBody className="space-y-5">
        {error && <p className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-3 py-2.5 text-sm text-[var(--danger-text)]" role="alert">{error}</p>}
        <form className="grid gap-3 md:grid-cols-[9rem_minmax(0,1fr)_9rem_auto] md:items-end" onSubmit={grantAccess}>
          <FormField htmlFor="access-principal-type" label="Type">
            <Select
              id="access-principal-type"
              onChange={(event) => {
                setPrincipalType(event.target.value as "user" | "group");
                setPrincipalId("");
              }}
              options={[{ value: "user", label: "Person" }, { value: "group", label: "Group" }]}
              value={principalType}
            />
          </FormField>
          <FormField htmlFor="access-principal" label={principalType === "user" ? "Person" : "Group"}>
            <Select id="access-principal" onChange={(event) => setPrincipalId(event.target.value)} options={availablePrincipals} value={principalId} />
          </FormField>
          <FormField htmlFor="access-role" label="Role">
            <Select
              id="access-role"
              onChange={(event) => setRole(event.target.value as "editor" | "viewer")}
              options={[{ value: "viewer", label: "Viewer" }, { value: "editor", label: "Editor" }]}
              value={role}
            />
          </FormField>
          <Button disabled={!principalId} icon={<UserPlus aria-hidden="true" className="h-4 w-4" />} loading={action === "grant"} type="submit">
            Add access
          </Button>
        </form>

        {grants.length ? (
          <div className="divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)]">
            {grants.map((grant) => {
              const name = principalName(grant, users, groups);
              const key = `${grant.principal_type}:${grant.principal_id}`;
              return (
                <div className="flex min-h-14 items-center gap-3 px-3 py-2.5" key={key}>
                  <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--primary-soft)] text-[var(--brand-accent)]">
                    <ShieldCheck aria-hidden="true" className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[var(--text)]">{name}</p>
                    <p className="text-xs text-[var(--text-muted)]">{titleCase(grant.principal_type)}</p>
                  </div>
                  <Badge>{titleCase(grant.role)}</Badge>
                  <Button
                    aria-label={`Remove ${grant.role} access for ${name}`}
                    disabled={grant.role === "owner"}
                    icon={<Trash2 aria-hidden="true" className="h-4 w-4" />}
                    loading={action === key}
                    onClick={() => revoke(grant)}
                    size="sm"
                    title={grant.role === "owner" ? "Transfer ownership before removing this owner" : undefined}
                    variant="ghost"
                  >
                    Remove
                  </Button>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState description="Add a person or group to make this knowledge base available beyond its creator." size="sm" title="No explicit access grants" />
        )}
      </CardBody>
    </Card>
  );
}

export function principalName(
  grant: CollectionGrant,
  users: DirectoryUser[],
  groups: DirectoryGroup[],
) {
  if (grant.principal_type === "user") {
    const user = users.find((candidate) => candidate.id === grant.principal_id);
    return user?.display_name || user?.email || grant.principal_id;
  }
  return groups.find((group) => group.id === grant.principal_id)?.display_name
    ?? grant.principal_id;
}
