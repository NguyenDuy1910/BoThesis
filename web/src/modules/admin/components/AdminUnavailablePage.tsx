import {
  ArrowRight,
  DatabaseZap,
  FileText,
  KeyRound,
  Layers,
  Plug,
  ScrollText,
  ShieldCheck,
  Users,
  UsersRound,
} from "lucide-react";
import Link from "next/link";

import { UnavailableState } from "@/components/ui/UnavailableState";

const sectionContent = {
  overview: {
    title: "Administration needs backend services",
    description: "The control plane is present, but this deployment does not expose the administration APIs required to read or change enterprise configuration.",
    icon: DatabaseZap,
  },
  connectors: {
    title: "Connector registry is unavailable",
    description: "Connector configuration, validation, synchronization, and lifecycle status require administration APIs that are not available in this deployment.",
    icon: Plug,
  },
  "ingestion/jobs": {
    title: "Ingestion status is not connected",
    description: "Ingestion jobs and indexing progress require administration APIs that are not available in this deployment.",
    icon: DatabaseZap,
  },
  items: {
    title: "Item management is not connected",
    description: "Source Item inventory, processing status, retry actions, and connector lineage require administration APIs that are not available in this deployment.",
    icon: FileText,
  },
  spaces: {
    title: "Spaces are not connected",
    description: "Workspace and organization boundaries require administration APIs that are not available in this deployment.",
    icon: Layers,
  },
  users: {
    title: "User management is not connected",
    description: "User identities and access assignments require identity and administration APIs that are not available in this deployment.",
    icon: Users,
  },
  groups: {
    title: "Group management is not connected",
    description: "Groups and membership assignments require administration APIs that are not available in this deployment.",
    icon: UsersRound,
  },
  "access-requests": {
    title: "Access Requests are not connected",
    description: "Access request review and approval require administration APIs that are not available in this deployment.",
    icon: KeyRound,
  },
  roles: {
    title: "Roles are not connected",
    description: "Role definitions and permission assignments require administration APIs that are not available in this deployment.",
    icon: ShieldCheck,
  },
  acl: {
    title: "ACL Policies are not connected",
    description: "Policy rules and resource-level access controls require administration APIs that are not available in this deployment.",
    icon: ShieldCheck,
  },
  "audit-logs": {
    title: "Audit Logs are not connected",
    description: "Operational audit records require administration APIs that are not available in this deployment.",
    icon: ScrollText,
  },
} as const;

export function AdminUnavailablePage({ section }: { section: string }) {
  const content = sectionContent[section as keyof typeof sectionContent] ?? sectionContent.overview;

  return (
    <UnavailableState
      actions={(
        <Link className="status-page__action" href="/app">
          Open knowledge workspace
          <ArrowRight aria-hidden="true" size={15} />
        </Link>
      )}
      className="admin-unavailable"
      description={content.description}
      details={[
        { label: "Interface", value: "Available" },
        { label: "Backend contract", value: "Not configured" },
      ]}
      eyebrow="Control plane status"
      icon={content.icon}
      title={content.title}
    />
  );
}
