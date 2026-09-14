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
import { ExperiencePage } from "@/modules/admin/pages/ExperiencePage";
import { PlatformAuditPage } from "@/modules/admin/pages/PlatformAuditPage";
import { PlatformIntegrationsPage } from "@/modules/admin/pages/PlatformIntegrationsPage";
import { PlatformModelsPage } from "@/modules/admin/pages/PlatformModelsPage";
import { PlatformPublicWorkspacesPage } from "@/modules/admin/pages/PlatformPublicWorkspacesPage";
import { PlatformTenantsPage } from "@/modules/admin/pages/PlatformTenantsPage";
import { PlatformUsagePage } from "@/modules/admin/pages/PlatformUsagePage";
import { PlatformUsersPage } from "@/modules/admin/pages/PlatformUsersPage";
import { SettingsPage } from "@/modules/admin/pages/SettingsPage";
import { SystemHealthPage } from "@/modules/admin/pages/SystemHealthPage";
import { WorkspaceOverviewPage } from "@/modules/admin/pages/WorkspaceOverviewPage";
import { WorkspaceKnowledgeScreen } from "@/modules/knowledge/components/WorkspaceKnowledgeScreen";

/**
 * The single entry point for every Admin address. It resolves the incoming
 * path to a canonical section — rewriting the address bar when an older link
 * is used — and hands off to the page that owns that section.
 *
 * The section ids come from the rails in `@/lib/navigation`, so a rail item
 * and the page it opens can never drift apart.
 */
export function AdminPage({ section: rawSection }: { section: string }) {
  const router = useRouter();
  const { section, canonicalPath, redirect } = resolveSection(rawSection);

  useEffect(() => {
    if (redirect) router.replace(canonicalPath);
  }, [canonicalPath, redirect, router]);

  switch (section) {
    // Workspace admin
    case "overview":
      return <WorkspaceOverviewPage />;
    case "knowledge":
      return <WorkspaceKnowledgeScreen />;
    case "agent":
      return <AgentsPoliciesPage />;
    case "access":
      return <AccessPage />;
    case "experience":
      return <ExperiencePage />;
    case "activity":
      return <AuditPage />;
    case "settings":
      return <SettingsPage />;

    // Platform admin
    case "platform-tenants":
      return <PlatformTenantsPage />;
    case "platform-users":
      return <PlatformUsersPage />;
    case "platform-public-workspaces":
      return <PlatformPublicWorkspacesPage />;
    case "platform-models":
      return <PlatformModelsPage />;
    case "platform-integrations":
      return <PlatformIntegrationsPage />;
    case "platform-usage":
      return <PlatformUsagePage />;
    case "platform-audit":
      return <PlatformAuditPage />;
    case "platform-system":
      return <SystemHealthPage />;

    default:
      return (
        <>
          <PageHeader
            description="This address is not part of the Admin console. It may have been renamed."
            title="Page not found"
          />
          <Card>
            <EmptyState
              action={<Button onClick={() => router.push("/admin")}>Go to the overview</Button>}
              description="Use the navigation, or press ⌘K to search for what you were looking for."
              icon={<Compass className="h-5 w-5" />}
              title="Nothing lives here"
            />
          </Card>
        </>
      );
  }
}
