"use client";

import { AtSign, CalendarPlus, ScrollText, ShieldCheck, UsersRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  Inspector,
  InspectorBody,
  InspectorFooter,
  InspectorHeader,
  InspectorMeta,
  InspectorRow,
  InspectorSection,
} from "@/components/layout/Inspector";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatDate } from "@/modules/admin/format";

export interface MemberRecord {
  id: string;
  display_name?: string | null;
  email?: string | null;
  status?: boolean;
  created_at?: string | null;
  membership?: { role?: { code?: string; display_name?: string } } | null;
  groups?: { display_name?: string }[] | null;
}

/**
 * One person's standing in this workspace.
 *
 * The panel is built to answer, in order: who is this, can they sign in, what
 * are they allowed to reach, and where did that permission come from. The
 * last question is the one an administrator cannot answer from a table, so
 * every access row states its origin rather than only its value.
 */
export function MemberInspector({
  member,
  onClose,
  onToggleStatus,
  busy,
}: {
  member: MemberRecord;
  onClose: () => void;
  onToggleStatus: (member: MemberRecord) => Promise<void> | void;
  busy: boolean;
}) {
  const router = useRouter();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const name = member.display_name || member.email || "Unnamed person";
  const role = member.membership?.role?.display_name;
  const groups = member.groups ?? [];
  const active = Boolean(member.status);

  return (
    <>
      <Inspector ariaLabel="Member details" onClose={onClose} open>
        <InspectorHeader
          avatarName={name}
          badge={role ? <Badge tone="brand">{role}</Badge> : undefined}
          onClose={onClose}
          subtitle={member.email ?? undefined}
          title={name}
        />
        <InspectorMeta
          items={[active ? "Can sign in" : "Sign-in disabled"]}
          status={
            <Badge dot tone={active ? "success" : "neutral"}>
              {active ? "Active" : "Disabled"}
            </Badge>
          }
        />
        <InspectorBody>
          <InspectorSection label="Access">
            <InspectorRow
              icon={ShieldCheck}
              subtitle={role ?? "No role assigned"}
              title="Workspace role"
              value="Direct assignment"
            />
            <InspectorRow
              icon={UsersRound}
              subtitle={
                groups.length
                  ? groups.map((group) => group.display_name).join(", ")
                  : "Not a member of any group"
              }
              title="Knowledge access"
              value={groups.length ? "Inherited from groups" : "Role only"}
            />
          </InspectorSection>

          <InspectorSection label="Account">
            <InspectorRow
              icon={AtSign}
              subtitle={member.email ?? "No address on file"}
              title="Email"
            />
            <InspectorRow
              icon={CalendarPlus}
              subtitle={formatDate(member.created_at)}
              title="Added"
            />
          </InspectorSection>
          <div className="h-4" />
        </InspectorBody>
        <InspectorFooter
          danger={
            <Button
              loading={busy}
              onClick={() => (active ? setConfirmOpen(true) : void onToggleStatus(member))}
              size="sm"
              variant={active ? "danger" : "secondary"}
            >
              {active ? "Disable access" : "Restore access"}
            </Button>
          }
        >
          <Button
            icon={<ScrollText aria-hidden="true" className="h-4 w-4" />}
            onClick={() => router.push("/admin/activity")}
            size="sm"
            variant="secondary"
          >
            View audit
          </Button>
        </InspectorFooter>
      </Inspector>

      {/* Restoring access is reversible and immediate; removing it is not, so
          only that direction is confirmed. */}
      <ConfirmDialog
        confirmLabel="Disable access"
        description={
          <>
            <strong>{name}</strong> will be signed out and will lose access to every
            collection, app and agent in this workspace. Their history and audit
            record are kept, and you can restore access later.
          </>
        }
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => {
          await onToggleStatus(member);
          setConfirmOpen(false);
        }}
        open={confirmOpen}
        title="Disable this person's access?"
      />
    </>
  );
}
