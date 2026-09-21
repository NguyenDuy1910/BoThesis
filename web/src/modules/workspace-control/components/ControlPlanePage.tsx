"use client";

import { Compass } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { resolveSection } from "@/modules/workspace-control/navigation";
import { AccessPage } from "@/modules/workspace-control/pages/AccessPage";
import { AgentsPoliciesPage } from "@/modules/workspace-control/pages/AgentsPoliciesPage";
import { AuditPage } from "@/modules/workspace-control/pages/AuditPage";
import { ExperiencePage } from "@/modules/workspace-control/pages/ExperiencePage";
import { PlatformAuditPage } from "@/modules/workspace-control/pages/PlatformAuditPage";
import { PlatformIntegrationsPage } from "@/modules/workspace-control/pages/PlatformIntegrationsPage";
import { PlatformModelsPage } from "@/modules/workspace-control/pages/PlatformModelsPage";
import { PlatformPublicWorkspacesPage } from "@/modules/workspace-control/pages/PlatformPublicWorkspacesPage";
import { PlatformTenantsPage } from "@/modules/workspace-control/pages/PlatformTenantsPage";
import { PlatformUsagePage } from "@/modules/workspace-control/pages/PlatformUsagePage";
import { PlatformUsersPage } from "@/modules/workspace-control/pages/PlatformUsersPage";
import { SettingsPage } from "@/modules/workspace-control/pages/SettingsPage";
import { SystemHealthPage } from "@/modules/workspace-control/pages/SystemHealthPage";
import { WorkspaceOverviewPage } from "@/modules/workspace-control/pages/WorkspaceOverviewPage";
import { KnowledgeScreen } from "@/modules/knowledge/components/KnowledgeScreen";

/**
 * The single entry point for every workspace-control address. It resolves the incoming
 * path to a canonical section — rewriting the address bar when an older link
 * is used — and hands off to the page that owns that section.
 *
 * The section ids come from the rails in `@/lib/navigation`, so a rail item
 * and the page it opens can never drift apart.
 */
export function ControlPlanePage({ section: rawSection }: { section: string }) {
  const router = useRouter();
  const { section, canonicalPath, redirect } = resolveSection(rawSection);

  useEffect(() => {
    if (redirect) router.replace(canonicalPath);
  }, [canonicalPath, redirect, router]);

  switch (section) {
    // Workspace control
    case "overview":
      return <WorkspaceOverviewPage />;
    case "knowledge":
      return <KnowledgeScreen />;
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

    // Platform control
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
            description="This address is not part of the workspace control surface. It may have been renamed."
            title="Page not found"
          />
          <Card>
            <EmptyState
              action={<Button onClick={() => router.push("/workspace-control")}>Go to the overview</Button>}
              description="Use the navigation, or press ⌘K to search for what you were looking for."
              icon={<Compass className="h-5 w-5" />}
              title="Nothing lives here"
            />
          </Card>
        </>
      );
  }
}
