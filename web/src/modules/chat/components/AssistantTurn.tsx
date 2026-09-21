"use client";

import clsx from "clsx";
import { Check, ChevronRight, CircleAlert, FileCog, LoaderCircle } from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";

import { assistantTurnItems, groupAssistantTurnItems } from "../assistant-turn";
import type { AnswerSource } from "../sources";
import type { RuntimeActivity, TurnState } from "../types";
import { appBrand } from "@/lib/brand";
import { ProductMark } from "@/components/ui/ProductMark";
import {
  CitationRenderingProvider,
  citationRenderingSources,
  IncrementalMarkdown,
} from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  activeCitationId,
  isStreaming,
  onOpenSource,
  onRevealingChange,
  showAgentActivity = true,
  sources,
  turn,
}: {
  activeCitationId?: string;
  isStreaming: boolean;
  onOpenSource?: (source: AnswerSource) => void;
  /** Report while the turn's newest text is still easing onto screen. */
  onRevealingChange?: (isRevealing: boolean) => void;
  showAgentActivity?: boolean;
  /** The citations this answer produced, for the inline chips. */
  sources?: readonly AnswerSource[];
  turn?: TurnState;
}) {
  const items = assistantTurnItems(turn);
  const renderItems = groupAssistantTurnItems(items);
  const pending = Boolean(isStreaming && turn?.modelPending);
  const { visible: showPending } = usePendingIndicator(pending);
  const hasRuntimeActivity = items.some((item) => item.kind === "activity");
  const revealingItemId = items.filter((item) => item.kind === "message").at(-1)?.id;
  const citations = useMemo(() => ({
    sources: citationRenderingSources(sources ?? []),
    activeCitationId,
    onOpenSource,
  }), [activeCitationId, onOpenSource, sources]);

  if (!items.length && !showPending) return null;

  return (
    <CitationRenderingProvider value={citations}>
      <div className="assistant-turn">
        {(isStreaming || hasRuntimeActivity) && (
          <div className="assistant-turn__identity">
            <ProductMark decorative size="sm" />
            <span className="assistant-turn__identity-name">{appBrand.productName} AI</span>
            <span className="assistant-turn__identity-badge">Grounded response</span>
          </div>
        )}
        {renderItems.map((item) => {
          if (item.kind === "message") {
            return (
              <div
                className={clsx("assistant-content", item.phase === "commentary" && "assistant-content--commentary")}
                data-assistant-phase={item.phase}
                key={item.id}
              >
                <IncrementalMarkdown
                  isStreaming={isStreaming && item.state === "streaming"}
                  onRevealingChange={item.id === revealingItemId ? onRevealingChange : undefined}
                  text={item.text}
                />
              </div>
            );
          }
          if (item.kind === "activity_group") {
            if (!showAgentActivity) return null;
            return (
              <ActivityGroup
                activities={item.activities}
                key={item.id}
              />
            );
          }
          return showAgentActivity ? <HostedExecutionActivity execution={item} key={item.id} /> : null;
        })}
        {showPending && (
          <span aria-label={`${appBrand.productName} is understanding the request`} className="assistant-turn__pending" role="status">
            Understanding the request
          </span>
        )}
      </div>
    </CitationRenderingProvider>
  );
});

function usePendingIndicator(pending: boolean) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!pending) {
      setVisible(false);
      return;
    }
    const timeout = window.setTimeout(() => setVisible(true), 700);
    return () => window.clearTimeout(timeout);
  }, [pending]);
  return { visible: pending && visible };
}

function HostedExecutionActivity({
  execution,
}: {
  execution: Extract<ReturnType<typeof assistantTurnItems>[number], { kind: "execution" }>;
}) {
  const active = execution.state === "running";
  const failed = execution.state === "failed" || execution.state === "timeout";
  const label = active
    ? "Working with your file"
    : execution.state === "timeout"
      ? "File work took too long"
      : execution.state === "failed"
        ? "Could not complete file work"
        : "File work completed";
  const Icon = active ? LoaderCircle : failed ? CircleAlert : Check;

  return (
    <details
      className={clsx("assistant-turn__execution", `assistant-turn__execution--${execution.state}`)}
      open={active || failed}
    >
      <summary aria-label={label}>
        <Icon aria-hidden="true" className="assistant-turn__execution-status" size={14} />
        <FileCog aria-hidden="true" className="assistant-turn__execution-terminal" size={16} />
        <span className="assistant-turn__execution-label">{label}</span>
        {execution.files.length > 0 && <span className="assistant-turn__execution-file-count">{execution.files.length} file{execution.files.length === 1 ? "" : "s"}</span>}
        <ChevronRight aria-hidden="true" className="assistant-turn__execution-caret" size={16} />
      </summary>
      <div className="assistant-turn__execution-body">
        {execution.files.length > 0 && (
          <p className="assistant-turn__execution-files">
            {execution.files.join(", ")}
          </p>
        )}
        {!execution.files.length && !active && <p>The workspace is ready for the next step.</p>}
      </div>
    </details>
  );
}

function ActivityGroup({
  activities,
}: {
  activities: RuntimeActivity[];
}) {
  const active = activities.some((activity) => activity.state === "active");
  const failed = activities.some((activity) => (
    activity.state === "failed" || activity.state === "timeout"
  ));
  const statusLabel = active ? "Working" : failed ? "Needs attention" : "Completed";
  return (
    <div
      aria-busy={active}
      aria-label={`${statusLabel}. ${activities.length} steps.`}
      className={clsx(
        "assistant-turn__activity-group",
        active && "assistant-turn__activity-group--active",
        failed && "assistant-turn__activity-group--failed",
      )}
      role="status"
    >
      <div className="assistant-turn__progress-heading">
        <span className="assistant-turn__progress-kicker">{statusLabel}</span>
        <span className="assistant-turn__progress-count">{activities.length} step{activities.length === 1 ? "" : "s"}</span>
      </div>
      <div className="assistant-turn__progress-list">
        {activities.map((activity) => <ToolActivity activity={activity} key={activity.callId} />)}
      </div>
    </div>
  );
}

function ToolActivity({ activity }: { activity: RuntimeActivity }) {
  const presentation = toolPresentation(activity);
  const active = activity.state === "active";
  const error = activity.state === "failed" || activity.state === "timeout";
  const elapsed = useElapsedSeconds(activity.startedAt, active);
  const Icon = active ? LoaderCircle : error ? CircleAlert : Check;
  const elapsedLabel = active && elapsed >= 10 ? `${elapsed}s` : undefined;
  const accessibleLabel = [presentation.label, presentation.detail, elapsedLabel]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      aria-label={accessibleLabel}
      className={clsx("assistant-turn__activity", "assistant-turn__progress-row", `assistant-turn__activity--${activity.state}`)}
      role={active ? "status" : undefined}
      title={accessibleLabel}
    >
      <span className="assistant-turn__progress-node">
        <Icon aria-hidden="true" className="assistant-turn__activity-icon" size={14} />
      </span>
      <span className="assistant-turn__progress-copy">
        <span className="assistant-turn__activity-label">{presentation.label}</span>
        {(presentation.detail || elapsedLabel) && (
          <span className="assistant-turn__progress-detail">
            {presentation.detail ?? elapsedLabel}
          </span>
        )}
      </span>
    </div>
  );
}

function useElapsedSeconds(startedAt: number, active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);
  return Math.max(0, Math.floor((now - startedAt) / 1_000));
}

function toolPresentation(activity: RuntimeActivity) {
  const active = activity.state === "active";
  const progressCount = numericProgress(activity.progress, "result_count");
  const resultCount = activity.resultCount ?? progressCount;
  const vocabulary: Record<string, { active: string; completed: string; showResultCount?: boolean }> = {
    knowledge_search: { active: "Searching company knowledge", completed: "Searched company knowledge", showResultCount: true },
    read_resource: { active: "Reading a source", completed: "Read a source" },
    inspect_resource: { active: "Inspecting a source", completed: "Inspected a source" },
    materialize_resource: { active: "Preparing a resource", completed: "Prepared a resource" },
    materialize_sandbox_resource: { active: "Preparing your file", completed: "Prepared your file" },
    export_sandbox_file: { active: "Saving a file", completed: "Saved a file" },
    document_edit: { active: "Editing a document", completed: "Edited a document" },
    artifact_create: { active: "Creating a document", completed: "Created a document" },
  };
  const text = vocabulary[activity.toolName] ?? {
    active: "Working on your request",
    completed: "Completed an action",
  };
  if (activity.state === "failed") return { label: "Could not complete an action", detail: undefined };
  if (activity.state === "timeout") return { label: "An action took too long", detail: undefined };
  if (activity.state === "skipped") return { label: "Skipped an action", detail: undefined };
  return {
    label: active ? text.active : text.completed,
    detail: !active && text.showResultCount && resultCount !== undefined
      ? `${resultCount} document${resultCount === 1 ? "" : "s"}`
      : undefined,
  };
}

function numericProgress(progress: Record<string, unknown> | undefined, key: string) {
  const value = progress?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
