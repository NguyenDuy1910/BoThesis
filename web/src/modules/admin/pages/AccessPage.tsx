"use client";

import {
  Check,
  KeyRound,
  Plus,
  ShieldCheck,
  UserPlus,
  Users,
  UsersRound,
  X,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CellTitle, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { getAuthSession, hasSessionPermission } from "@/lib/auth/session";
import { Tooltip } from "@/components/ui/Tooltip";
import { adminRequest, queryString, useAdminQuery } from "@/modules/admin/api";
import type { Paginated } from "@/modules/admin/collections";
import { AccessCreateDialog } from "@/modules/admin/components/AccessCreateDialog";
import { ResourceList } from "@/modules/admin/components/ResourceList";
import {
  errorMessage,
  formatRelative,
  pluralize,
  titleCase,
} from "@/modules/admin/format";

type AccessTab = "people" | "groups" | "roles" | "requests";

type Row = Record<string, any>;

const PAGE_SIZE = 25;

/**
 * Access used to be five sidebar entries for one question — who can reach
 * what. They are one section now, because an administrator answering that
 * question moves between them constantly.
 */
const tabConfig: Record<
  AccessTab,
  {
    label: string;
    endpoint: string;
    createLabel?: string;
    emptyTitle: string;
    emptyDescription: string;
    icon: typeof Users;
    permissionCode: string;
  }
> = {
  people: {
    label: "People",
    endpoint: "/users",
    createLabel: "Invite person",
    emptyTitle: "No one else has been added",
    emptyDescription:
      "Invite colleagues so they can search this workspace's knowledge with their own permissions.",
    icon: Users,
    permissionCode: "user.manage",
  },
  groups: {
    label: "Groups",
    endpoint: "/groups",
    createLabel: "Create group",
    emptyTitle: "No groups yet",
    emptyDescription:
      "Groups let you grant a whole team access to a collection in one step instead of person by person.",
    icon: UsersRound,
    permissionCode: "group.manage",
  },
  roles: {
    label: "Roles",
    endpoint: "/roles",
    createLabel: "Create role",
    emptyTitle: "No roles defined",
    emptyDescription:
      "A role bundles the actions someone can take in the console, such as managing sources or approving requests.",
    icon: ShieldCheck,
    permissionCode: "role.manage",
  },
  requests: {
    label: "Requests",
    endpoint: "/access-requests",
    emptyTitle: "No pending requests",
    emptyDescription:
      "When someone asks for access to a collection, their request lands here for you to approve or decline.",
    icon: KeyRound,
    permissionCode: "access.manage",
  },
};

const tabOrder: AccessTab[] = ["people", "groups", "roles", "requests"];

function readTab(value: string | null, availableTabs: readonly AccessTab[]): AccessTab {
  const requested = value as AccessTab;
  return availableTabs.includes(requested) ? requested : availableTabs[0];
}

export function AccessPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const availableTabs = useMemo(
    () => tabOrder.filter((id) =>
      hasSessionPermission(getAuthSession(), tabConfig[id].permissionCode),
    ),
    [],
  );
  // Keep hook execution stable for a direct, unauthorized URL. The guarded
  // render below deliberately makes no request in that case.
  const selectableTabs: readonly AccessTab[] = availableTabs.length
    ? availableTabs
    : ["people"];

  const [tab, setTab] = useState<AccessTab>(() =>
    readTab(searchParams.get("tab"), selectableTabs),
  );
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const config = tabConfig[tab];
  const list = useAdminQuery<Paginated<Row>>(
    availableTabs.length
      ? `${config.endpoint}${queryString({ page, page_size: PAGE_SIZE, search })}`
      : null,
  );
  const pendingRequests = useAdminQuery<Paginated<Row>>(
    hasSessionPermission(getAuthSession(), "access.manage")
      ? "/access-requests?status=pending&page_size=1"
      : null,
  );

  const changeTab = useCallback(
    (next: string) => {
      const value = readTab(next, selectableTabs);
      setTab(value);
      setPage(1);
      setSearch("");
      const params = new URLSearchParams(searchParams.toString());
      if (value === "people") params.delete("tab");
      else params.set("tab", value);
      router.replace(`${pathname}${params.size ? `?${params}` : ""}`, {
        scroll: false,
      });
    },
    [pathname, router, searchParams, selectableTabs],
  );

  useEffect(() => {
    if (!availableTabs.length) return;
    if (availableTabs.includes(tab)) return;
    changeTab(availableTabs[0]);
  }, [availableTabs, changeTab, tab]);

  const mutate = useCallback(
    async (id: string, label: string, path: string, method: string, body?: unknown) => {
      setBusyId(id);
      try {
        await adminRequest(path, {
          method,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        toast({ title: label, variant: "success" });
        list.reload();
        pendingRequests.reload();
      } catch (cause) {
        toast({
          title: `${label} failed`,
          description: errorMessage(cause),
          variant: "error",
        });
      } finally {
        setBusyId(null);
      }
    },
    [list, pendingRequests, toast],
  );

  const columns = useMemo<Column<Row>[]>(() => {
    if (tab === "people") {
      return [
        {
          key: "display_name",
          label: "Person",
          sortable: true,
          render: (row) => (
            <CellTitle
              icon={<Avatar name={row.display_name || row.email} size="md" />}
              subtitle={row.email}
              title={row.display_name || row.email}
            />
          ),
        },
        {
          key: "role",
          label: "Role",
          priority: "medium",
          minWidth: 150,
          render: (row) => row.membership?.role?.display_name ?? "No role",
        },
        {
          key: "groups",
          label: "Groups",
          priority: "low",
          minWidth: 160,
          render: (row) =>
            row.groups?.length
              ? row.groups.map((group: Row) => group.display_name).join(", ")
              : "—",
        },
        {
          key: "status",
          label: "Status",
          width: 120,
          render: (row) => <StatusBadge status={row.status} />,
        },
        {
          key: "last_login_at",
          label: "Last active",
          width: 130,
          render: (row) => formatRelative(row.last_login_at, "Never signed in"),
        },
      ];
    }
    if (tab === "groups") {
      return [
        {
          key: "display_name",
          label: "Group",
          sortable: true,
          render: (row) => (
            <CellTitle
              icon={<Avatar name={row.display_name} size="md" />}
              subtitle={row.description || "No description"}
              title={row.display_name}
            />
          ),
        },
        {
          key: "member_count",
          label: "Members",
          align: "right",
          width: 100,
          render: (row) => (row.member_count ?? 0).toLocaleString(),
        },
        {
          key: "permission_codes",
          label: "Permissions",
          align: "right",
          priority: "low",
          width: 120,
          render: (row) => (row.permission_codes?.length ?? 0).toLocaleString(),
        },
        {
          key: "status",
          label: "Status",
          width: 120,
          render: (row) => <StatusBadge status={row.status} />,
        },
        {
          key: "updated_at",
          label: "Updated",
          width: 130,
          render: (row) => formatRelative(row.updated_at),
        },
      ];
    }
    if (tab === "roles") {
      return [
        {
          key: "display_name",
          label: "Role",
          sortable: true,
          render: (row) => (
            <CellTitle subtitle={row.description || row.code} title={row.display_name} />
          ),
        },
        {
          key: "member_count",
          label: "People",
          align: "right",
          width: 90,
          render: (row) => (row.member_count ?? 0).toLocaleString(),
        },
        {
          key: "permission_codes",
          label: "Can do",
          minWidth: 240,
          render: (row) =>
            row.permission_codes?.length ? (
              <span className="flex flex-wrap gap-1">
                {row.permission_codes.slice(0, 3).map((code: string) => (
                  <Badge key={code} tone="neutral">
                    {code.replace(/[._]/g, " ")}
                  </Badge>
                ))}
                {row.permission_codes.length > 3 && (
                  <Badge tone="neutral">+{row.permission_codes.length - 3}</Badge>
                )}
              </span>
            ) : (
              <span className="text-[var(--text-muted)]">Nothing yet</span>
            ),
        },
        {
          key: "status",
          label: "Status",
          width: 120,
          render: (row) => <StatusBadge status={row.status} />,
        },
      ];
    }
    if (tab === "requests") {
      return [
        {
          key: "requester",
          label: "Requested by",
          render: (row) => {
            const name = row.requester?.display_name || row.requester?.email || "Unknown";
            return (
              <CellTitle
                icon={<Avatar name={name} size="md" />}
                subtitle={row.requester?.email}
                title={name}
              />
            );
          },
        },
        {
          key: "resource_type",
          label: "Wants access to",
          minWidth: 200,
          render: (row) => (
            <span>
              {titleCase(row.resource_type)}
              {row.access_type && (
                <span className="text-[var(--text-muted)]"> · {row.access_type}</span>
              )}
            </span>
          ),
        },
        {
          key: "reason",
          label: "Reason",
          priority: "low",
          minWidth: 200,
          render: (row) => row.reason || <span className="text-[var(--text-muted)]">Not given</span>,
        },
        {
          key: "status",
          label: "Status",
          width: 120,
          render: (row) => <StatusBadge status={row.status} />,
        },
        {
          key: "created_at",
          label: "Asked",
          width: 120,
          render: (row) => formatRelative(row.created_at),
        },
      ];
    }
    return [
      {
        key: "name",
        label: "Policy",
        minWidth: 240,
        sortable: true,
        render: (row) => (
          <CellTitle
            subtitle={row.resource_title ?? "One collection"}
            title={row.name}
          />
        ),
      },
      {
        key: "allowed",
        label: "Allowed",
        align: "right",
        width: 100,
        render: (row) => (row.allowed_principal_tokens?.length ?? 0).toLocaleString(),
      },
      {
        key: "denied",
        label: "Denied",
        align: "right",
        width: 100,
        render: (row) => (row.denied_principal_tokens?.length ?? 0).toLocaleString(),
      },
      {
        key: "status",
        label: "Status",
        width: 120,
        render: (row) => <StatusBadge status={row.status} />,
      },
      {
        key: "updated_at",
        label: "Updated",
        width: 130,
        render: (row) => formatRelative(row.updated_at),
      },
    ];
  }, [tab]);

  const rowActions = useCallback(
    (row: Row) => {
      if (tab === "requests") {
        if (row.status !== "pending") return null;
        return (
          <>
            <Button
              icon={<Check aria-hidden="true" className="h-3.5 w-3.5" />}
              loading={busyId === row.id}
              onClick={() =>
                mutate(
                  row.id,
                  "Access granted",
                  `/access-requests/${row.id}/decision`,
                  "POST",
                  { decision: "approved" },
                )
              }
              size="sm"
              variant="secondary"
            >
              Approve
            </Button>
            <Tooltip label="Decline request" side="top">
              <Button
                aria-label="Decline request"
                icon={<X aria-hidden="true" className="h-3.5 w-3.5" />}
                iconOnly
                loading={busyId === row.id}
                onClick={() =>
                  mutate(
                    row.id,
                    "Request declined",
                    `/access-requests/${row.id}/decision`,
                    "POST",
                    { decision: "denied" },
                  )
                }
                size="sm"
                variant="ghost"
              />
            </Tooltip>
          </>
        );
      }

      const endpoint = tabConfig[tab].endpoint;
      const disabling = row.status === "active";
      return (
        <Button
          loading={busyId === row.id}
          onClick={() =>
            mutate(
              row.id,
              disabling ? "Disabled" : "Enabled",
              `${endpoint}/${row.id}`,
              "PATCH",
              { status: disabling ? "inactive" : "active" },
            )
          }
          size="sm"
          variant={disabling ? "danger" : "secondary"}
        >
          {disabling ? "Disable" : "Enable"}
        </Button>
      );
    },
    [busyId, mutate, tab],
  );

  const pendingCount = pendingRequests.data?.total ?? 0;
  const EmptyIcon = config.icon;

  if (!availableTabs.length) {
    return (
      <EmptyState
        description="Your active workspace role does not include access administration."
        icon={<ShieldCheck className="h-5 w-5" />}
        title="Access administration is unavailable"
      />
    );
  }

  return (
    <>
      <PageHeader
        actions={
          config.createLabel && (
            <Button
              icon={
                tab === "people" ? (
                  <UserPlus aria-hidden="true" className="h-4 w-4" />
                ) : (
                  <Plus aria-hidden="true" className="h-4 w-4" />
                )
              }
              onClick={() => setCreateOpen(true)}
            >
              {config.createLabel}
            </Button>
          )
        }
        description="Who belongs to this workspace, and what each person is allowed to reach."
        title="Access"
      />

      <Tabs
        activeTab={tab}
        ariaLabel="Access sections"
        className="mb-4"
        onChange={changeTab}
        tabs={availableTabs.map((id) => ({
          id,
          label: tabConfig[id].label,
          count: id === "requests" && pendingCount ? pendingCount : undefined,
        }))}
      />

      <ResourceList
        ariaLabel={config.label}
        columns={columns}
        empty={
          <EmptyState
            action={
              config.createLabel && (
                <Button onClick={() => setCreateOpen(true)}>{config.createLabel}</Button>
              )
            }
            description={config.emptyDescription}
            icon={<EmptyIcon className="h-5 w-5" />}
            title={config.emptyTitle}
          />
        }
        error={list.error}
        filtersActive={Boolean(search)}
        loading={list.loading}
        onClearFilters={() => {
          setSearch("");
          setPage(1);
        }}
        onRetry={list.reload}
        pagination={{
          page,
          pageSize: PAGE_SIZE,
          total: list.data?.total ?? 0,
          onPageChange: setPage,
        }}
        rows={list.data?.items ?? []}
        rowActions={rowActions}
        toolbar={
          <>
            <SearchInput
              ariaLabel={`Search ${config.label.toLowerCase()}`}
              className="w-full sm:w-72"
              onChange={(value) => {
                setSearch(value);
                setPage(1);
              }}
              placeholder={`Search ${config.label.toLowerCase()}…`}
              value={search}
            />
            <div className="adm-toolbar__spacer" />
            {list.data && (
              <p className="text-[0.75rem] text-[var(--text-muted)]">
                {pluralize(list.data.total, "record")}
              </p>
            )}
          </>
        }
      />

      {createOpen && config.createLabel && (
        <AccessCreateDialog
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            list.reload();
          }}
          tab={tab}
        />
      )}
    </>
  );
}
