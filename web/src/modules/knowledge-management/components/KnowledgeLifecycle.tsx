import { Check, CircleAlert, CircleDashed, Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";
import type { KnowledgeItem, PluginBinding, SyncRun } from "@/modules/knowledge-management/types";

type LifecycleState = "complete" | "current" | "waiting" | "error";

export function KnowledgeLifecycle({
  bindings,
  documents,
  runs,
}: {
  bindings: PluginBinding[];
  documents: KnowledgeItem[];
  runs: SyncRun[];
}) {
  const hasBinding = bindings.length > 0;
  const hasScope = bindings.some((binding) => binding.status === "active");
  const hasCompletedSync = runs.some((run) => run.status === "completed");
  const syncActive = runs.some((run) => run.status === "pending" || run.status === "running");
  const failed = runs.some((run) => run.status === "failed") || documents.some((item) => item.status === "failed");
  const indexedCount = documents.filter((item) => item.indexed).length;
  const ready = documents.length > 0 && indexedCount === documents.length && documents.every((item) => item.status === "ready");

  const steps: Array<{ label: string; detail: string; state: LifecycleState }> = [
    {
      label: "Connected",
      detail: hasBinding ? `${bindings.length} governed source${bindings.length === 1 ? "" : "s"}` : "Connect a source",
      state: hasBinding ? "complete" : "current",
    },
    {
      label: "Scoped",
      detail: hasScope ? "Content boundary saved" : "Define included content",
      state: hasScope ? "complete" : hasBinding ? "current" : "waiting",
    },
    {
      label: "Synced",
      detail: syncActive ? "Discovery is running" : hasCompletedSync ? "Source discovery complete" : failed ? "Sync needs attention" : "Waiting for first sync",
      state: failed && !hasCompletedSync ? "error" : hasCompletedSync ? "complete" : syncActive ? "current" : "waiting",
    },
    {
      label: "Indexed",
      detail: documents.length ? `${indexedCount} of ${documents.length} documents` : "No supported content yet",
      state: failed && indexedCount < documents.length ? "error" : indexedCount > 0 && indexedCount === documents.length ? "complete" : documents.length ? "current" : "waiting",
    },
    {
      label: "Search-ready",
      detail: ready ? "Available for grounded answers" : "Indexing must finish first",
      state: ready ? "complete" : "waiting",
    },
  ];

  return (
    <ol aria-label="Knowledge readiness" className="knowledge-lifecycle">
      {steps.map((step, index) => (
        <li className={cn("knowledge-lifecycle__step", `knowledge-lifecycle__step--${step.state}`)} key={step.label}>
          <span aria-hidden="true" className="knowledge-lifecycle__marker">
            {step.state === "complete" ? <Check /> : step.state === "current" ? <Loader2 className="motion-safe:animate-spin" /> : step.state === "error" ? <CircleAlert /> : <CircleDashed />}
          </span>
          <span className="min-w-0">
            <strong>{step.label}</strong>
            <small>{step.detail}</small>
          </span>
          {index < steps.length - 1 && <span aria-hidden="true" className="knowledge-lifecycle__line" />}
        </li>
      ))}
    </ol>
  );
}
