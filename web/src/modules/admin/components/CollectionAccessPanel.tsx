"use client";

import { Trash2, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { FormField } from "@/components/ui/FormField";
import { Select } from "@/components/ui/Select";
import { Tooltip } from "@/components/ui/Tooltip";
import { useToast } from "@/components/ui/Toast";
import { adminRequest } from "@/modules/admin/api";
import type {
  CollectionGrant,
  DirectoryGroup,
  DirectoryUser,
} from "@/modules/admin/collections";
import { errorMessage, titleCase } from "@/modules/admin/format";

const roleDescriptions: Record<string, string> = {
  owner: "Full control, including deleting the collection",
  editor: "Can add and remove content",
  viewer: "Can search and read",
};

export function principalName(
  grant: CollectionGrant,
  users: DirectoryUser[],
  groups: DirectoryGroup[],
) {
  if (grant.principal_type === "user") {
    const user = users.find((candidate) => candidate.id === grant.principal_id);
    return user?.display_name || user?.email || "Unknown person";
  }
  return (
    groups.find((group) => group.id === grant.principal_id)?.display_name ??
    "Unknown group"
  );
}

export function CollectionAccessPanel({
  collectionId,
  grants,
  groups,
  inheritAccess,
  onChanged,
  users,
}: {
  collectionId: string;
  grants: CollectionGrant[];
  groups: DirectoryGroup[];
  inheritAccess: boolean;
  onChanged: () => void;
  users: DirectoryUser[];
}) {
  const { toast } = useToast();
  const [principalType, setPrincipalType] = useState<"user" | "group">("user");
  const [principalId, setPrincipalId] = useState("");
  const [role, setRole] = useState<"editor" | "viewer">("viewer");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const alreadyGranted = useMemo(
    () => new Set(grants.map((grant) => `${grant.principal_type}:${grant.principal_id}`)),
    [grants],
  );

  const principalOptions = useMemo(() => {
    const entries =
      principalType === "user"
        ? users
            .filter((user) => user.status === "active")
            .map((user) => ({ value: user.id, label: user.display_name || user.email }))
        : groups
            .filter((group) => group.status === "active")
            .map((group) => ({ value: group.id, label: group.display_name }));
    return [
      { value: "", label: principalType === "user" ? "Choose a person" : "Choose a group" },
      ...entries.filter((entry) => !alreadyGranted.has(`${principalType}:${entry.value}`)),
    ];
  }, [alreadyGranted, groups, principalType, users]);

  async function grantAccess(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!principalId || pending) return;
    setPending("grant");
    setError(null);
    try {
      await adminRequest(`/collections/${collectionId}/access`, {
        method: "PUT",
        body: JSON.stringify({
          principal_type: principalType,
          principal_id: principalId,
          role,
        }),
      });
      toast({ title: "Access granted", variant: "success" });
      setPrincipalId("");
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause, "Access could not be granted."));
    } finally {
      setPending(null);
    }
  }

  async function revoke(grant: CollectionGrant) {
    const key = `${grant.principal_type}:${grant.principal_id}`;
    setPending(key);
    setError(null);
    try {
      await adminRequest(
        `/collections/${collectionId}/access/${grant.principal_type}/${grant.principal_id}`,
        { method: "DELETE" },
      );
      toast({ title: "Access removed", variant: "success" });
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause, "Access could not be removed."));
    } finally {
      setPending(null);
    }
  }

  return (
    <Card>
      <CardHeader
        description={
          inheritAccess
            ? "People below can reach this collection. Permissions from the original source are also enforced before anything is returned."
            : "Only the people and groups listed below can reach this collection."
        }
        title="Who can access this"
      />
      <CardBody className="space-y-4">
        {error && <ErrorState description={error} layout="inline" />}

        <form
          className="grid gap-2.5 sm:grid-cols-[8rem_minmax(0,1fr)_8rem_auto] sm:items-end"
          onSubmit={grantAccess}
        >
          <FormField htmlFor="grant-type" label="Add" required>
            <Select
              id="grant-type"
              onChange={(event) => {
                setPrincipalType(event.target.value as "user" | "group");
                setPrincipalId("");
              }}
              options={[
                { value: "user", label: "A person" },
                { value: "group", label: "A group" },
              ]}
              value={principalType}
            />
          </FormField>
          <FormField
            htmlFor="grant-principal"
            label={principalType === "user" ? "Person" : "Group"}
            required
          >
            <Select
              id="grant-principal"
              onChange={(event) => setPrincipalId(event.target.value)}
              options={principalOptions}
              value={principalId}
            />
          </FormField>
          <FormField htmlFor="grant-role" label="Can" required>
            <Select
              id="grant-role"
              onChange={(event) => setRole(event.target.value as "editor" | "viewer")}
              options={[
                { value: "viewer", label: "Read" },
                { value: "editor", label: "Edit" },
              ]}
              value={role}
            />
          </FormField>
          <Button
            disabled={!principalId}
            icon={<UserPlus aria-hidden="true" className="h-4 w-4" />}
            loading={pending === "grant"}
            type="submit"
          >
            Add
          </Button>
        </form>

        {grants.length > 0 && (
          <ul className="divide-y divide-[var(--adm-hairline)] overflow-hidden rounded-[var(--adm-r-md)] shadow-[inset_0_0_0_1px_var(--adm-hairline)]">
            {grants.map((grant) => {
              const name = principalName(grant, users, groups);
              const key = `${grant.principal_type}:${grant.principal_id}`;
              const isOwner = grant.role === "owner";
              return (
                <li className="flex items-center gap-3 px-3 py-2.5" key={key}>
                  <Avatar name={name} size="md" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[0.8125rem] font-medium text-[var(--text)]">
                      {name}
                    </p>
                    <p className="text-[0.75rem] text-[var(--text-muted)]">
                      {grant.principal_type === "group" ? "Group" : "Person"} ·{" "}
                      {roleDescriptions[grant.role] ?? titleCase(grant.role)}
                    </p>
                  </div>
                  <Badge tone={isOwner ? "brand" : "neutral"}>
                    {titleCase(grant.role)}
                  </Badge>
                  <Tooltip
                    label={
                      isOwner
                        ? "Owners cannot be removed here"
                        : `Remove ${name}'s access`
                    }
                    side="top"
                  >
                    <Button
                      aria-label={`Remove access for ${name}`}
                      disabled={isOwner}
                      icon={<Trash2 aria-hidden="true" className="h-3.5 w-3.5" />}
                      iconOnly
                      loading={pending === key}
                      onClick={() => revoke(grant)}
                      size="sm"
                      variant="ghost"
                    />
                  </Tooltip>
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
