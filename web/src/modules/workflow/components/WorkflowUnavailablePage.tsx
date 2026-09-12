"use client";

import Link from "next/link";
import { ArrowLeft, Workflow } from "lucide-react";

import { GlobalAssistantLauncher } from "@/components/ui/GlobalAssistantLauncher";
import { ProductMark } from "@/components/ui/ProductMark";
import { ProductSidebarGlobalNavigation } from "@/components/ui/ProductSidebarGlobalNavigation";
import { UnavailableState } from "@/components/ui/UnavailableState";
import { appBrand } from "@/lib/brand";

export function WorkflowUnavailablePage() {
  return (
    <div className="unavailable-product-shell">
      <aside className="unavailable-product-sidebar">
        <Link className="unavailable-product-sidebar__brand" href="/app" aria-label={appBrand.productName}>
          <ProductMark decorative size="md" />
          <span>{appBrand.productName}</span>
        </Link>
        <ProductSidebarGlobalNavigation />
      </aside>
      <main className="status-page unavailable-product-main" id="main-content">
        <header className="status-page__header">
          <span className="status-page__context">Agents &amp; Skills</span>
        </header>
        <UnavailableState
          description="The agent library needs durable backend contracts for agents, skills, tools, and evaluations. It remains clearly unavailable instead of showing invented agents or workflows."
          details={[
            { label: "Agent library", value: "Backend required" },
            { label: "Skills & tools", value: "Backend required" },
          ]}
          eyebrow="Capability status"
          icon={Workflow}
          title="Agents & Skills are not connected"
          actions={(
            <Link className="status-page__action" href="/app">
              <ArrowLeft aria-hidden="true" size={15} />
              Return to chat
            </Link>
          )}
        />
      </main>
      <GlobalAssistantLauncher />
    </div>
  );
}
