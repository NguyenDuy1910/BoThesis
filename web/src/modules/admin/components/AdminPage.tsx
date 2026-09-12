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
import { ActivityPage } from "@/modules/admin/pages/ActivityPage";
import { AuditPage } from "@/modules/admin/pages/AuditPage";
import { AppsPage } from "@/modules/admin/pages/AppsPage";
import { DashboardPage } from "@/modules/admin/pages/DashboardPage";
import { SchedulesPage } from "@/modules/admin/pages/SchedulesPage";
import { SettingsPage } from "@/modules/admin/pages/SettingsPage";

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
    case "dashboard":
      return <DashboardPage />;
    case "connectors":
      return <AppsPage />;
    case "schedules":
      return <SchedulesPage />;
    case "activity":
      return <ActivityPage />;
    case "access":
      return <AccessPage />;
    case "audit":
      return <AuditPage />;
    case "settings":
      return <SettingsPage />;
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
