import Link from "next/link";
import { ArrowLeft, Workflow } from "lucide-react";

import { ProductMark } from "@/components/ui/ProductMark";
import { UnavailableState } from "@/components/ui/UnavailableState";

export function WorkflowUnavailablePage() {
  return (
    <main className="status-page" id="main-content">
      <header className="status-page__header">
        <Link className="status-page__brand" href="/app" aria-label="BoThesis knowledge workspace">
          <ProductMark decorative size="sm" />
          <span>BoThesis</span>
        </Link>
        <span className="status-page__context">Workflow studio</span>
      </header>
      <UnavailableState
        description="Workflow authoring and execution depend on backend contracts that are not available in this deployment. The route remains visible so the product structure stays predictable without inventing unsupported workflows."
        details={[
          { label: "Authoring", value: "Backend required" },
          { label: "Execution", value: "Backend required" },
        ]}
        eyebrow="Capability status"
        icon={Workflow}
        title="Workflow studio is not connected"
        actions={(
          <Link className="status-page__action" href="/app">
            <ArrowLeft aria-hidden="true" size={15} />
            Return to knowledge workspace
          </Link>
        )}
      />
    </main>
  );
}
