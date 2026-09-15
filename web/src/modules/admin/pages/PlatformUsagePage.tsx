"use client";

import { NotBackedYet } from "@/components/ui/NotBackedYet";

export function PlatformUsagePage() {
  return (
    <NotBackedYet
      description="Conversation volume, indexed document counts and model spend per workspace will be reported here. No endpoint aggregates usage yet."
      title="Usage reporting is not available yet"
    />
  );
}
