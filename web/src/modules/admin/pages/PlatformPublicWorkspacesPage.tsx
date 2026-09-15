"use client";

import { NotBackedYet } from "@/components/ui/NotBackedYet";

export function PlatformPublicWorkspacesPage() {
  return (
    <NotBackedYet
      description="Listing a workspace for discovery, and choosing the one a new signed-in person lands in, will be managed here. Workspace visibility is not part of the data model yet, so there is nothing to read or write."
      title="Public workspaces are not stored yet"
    />
  );
}
