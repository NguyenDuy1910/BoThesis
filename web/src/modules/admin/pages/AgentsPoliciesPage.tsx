"use client";

import { NotBackedYet } from "@/components/ui/NotBackedYet";

export function AgentsPoliciesPage() {
  return (
    <NotBackedYet
      description="The agent's name, instructions, model and tool permissions will be configured here and stored per workspace. No endpoint stores them yet, so nothing on this screen would persist."
      title="Agent configuration is not stored yet"
    />
  );
}
