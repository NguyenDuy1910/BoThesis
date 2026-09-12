"use client";

import { Bot, ExternalLink } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

/** The current API has an agent library but no durable workspace policy resource. */
export function AgentsPoliciesPage() {
  return (
    <>
      <PageHeader description="Governance for shared agents, tools, skills, and external action approvals belongs here." title="Agents & policies" />
      <EmptyState
        action={<Link href="/app"><Button icon={<ExternalLink aria-hidden="true" className="h-4 w-4" />}>Open agents</Button></Link>}
        description="The current API does not yet expose a durable workspace agent-policy resource. The agent library remains available, but policy controls are not shown as if they were configured."
        icon={<Bot className="h-5 w-5" />}
        title="Agent policies are not available yet"
      />
    </>
  );
}
