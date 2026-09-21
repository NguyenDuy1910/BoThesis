"use client";

import { NotBackedYet } from "@/components/ui/NotBackedYet";

export function PlatformPublicWorkspacesPage() {
  return (
    <NotBackedYet
      description="Guest entry now uses the public workspace configured by the deployment. A platform endpoint for listing and changing public workspaces is not available yet."
      title="Public workspace policy is deployment-managed"
    />
  );
}
