"use client";

import { Compass } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { resolveSection } from "@/modules/admin/navigation";
import { AccessPage } from "@/modules/admin/pages/AccessPage";
import { AgentsPoliciesPage } from "@/modules/admin/pages/AgentsPoliciesPage";
import { AuditPage } from "@/modules/admin/pages/AuditPage";
import { KnowledgeGovernancePage } from "@/modules/admin/pages/KnowledgeGovernancePage";
import { PlatformOverviewPage } from "@/modules/admin/pages/PlatformOverviewPage";
import { PlatformAuditPage } from "@/modules/admin/pages/PlatformAuditPage";
import { PlatformPoliciesPage } from "@/modules/admin/pages/PlatformPoliciesPage";
import { PlatformUsersPage } from "@/modules/admin/pages/PlatformUsersPage";
import { PlatformWorkspacesPage } from "@/modules/admin/pages/PlatformWorkspacesPage";
import { SystemHealthPage } from "@/modules/admin/pages/SystemHealthPage";
import { SettingsPage } from "@/modules/admin/pages/SettingsPage";
import { WorkspaceOverviewPage } from "@/modules/admin/pages/WorkspaceOverviewPage";

/**
 * The single entry point for every Admin address. It resolves the incoming
 * path to a canonical section — rewriting the address bar when an older link
 * is used — and hands off to the page that owns that section.
 */
export function AdminPage({ section: rawSection }: { section: string }) {
  const router = useRouter();
  const { section, canonicalPath, redirect } = resolveSection(rawSection);

  useEffect(() => {
    if (redirect) router.replace(canonicalPath);
  }, [canonicalPath, redirect, router]);

  switch (section) {
    case "overview":
      return <WorkspaceOverviewPage />;
    case "members":
      return <AccessPage initialTab="people" title="Members & access" />;
    case "roles":
      return <AccessPage initialTab="roles" title="Roles & access" />;
    case "knowledge-governance":
      return <KnowledgeGovernancePage />;
    case "agents-policies":
      return <AgentsPoliciesPage />;
    case "audit":
      return <AuditPage />;
    case "settings":
      return <SettingsPage />;
    case "platform-overview":
      return <PlatformOverviewPage />;
    case "platform-workspaces":
      return <PlatformWorkspacesPage />;
    case "platform-users":
      return <PlatformUsersPage />;
    case "platform-policies":
      return <PlatformPoliciesPage />;
    case "platform-health":
      return <SystemHealthPage />;
    case "platform-audit":
      return <PlatformAuditPage />;
    default:
      return (
        <>
          <PageHeader
            description="This address is not part of the Admin console. It may have been renamed."
            title="Page not found"
          />
          <Card>
            <EmptyState
              action={
                <Button onClick={() => router.push("/admin")}>
                  Go to the dashboard
                </Button>
              }
              description="Use the navigation, or press ⌘K to search for what you were looking for."
              icon={<Compass className="h-5 w-5" />}
              title="Nothing lives here"
            />
          </Card>
        </>
      );
  }
}
