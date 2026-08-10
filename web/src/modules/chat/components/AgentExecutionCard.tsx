"use client";

import clsx from "clsx";
import {
  AlertCircle,
  BookOpen,
  Check,
  CircleStop,
  Clock3,
  Database,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  FileType,
  LoaderCircle,
  Search,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";

import { AgentActivityMapper } from "@/modules/chat/activity-mapper";
import type { ActivityEntry, AgentRunStatus, SourceResult, SourceType } from "@/modules/chat/activity";
import type { ChatMessage } from "@/modules/chat/types";

interface SourceFocus {
  sourceId: string;
  nonce: number;
}

interface AgentExecutionCardProps {
  message: ChatMessage;
  isStreaming: boolean;
  onOpen: () => void;
}

export const AgentExecutionCard = memo(function AgentExecutionCard({
  message,
  isStreaming,
  onOpen,
}: AgentExecutionCardProps) {
  const run = useMemo(
    () => AgentActivityMapper.fromParts(message.parts, isStreaming),
    [message.parts, isStreaming],
  );
  if (!run.hasActivity) return null;

  return (
    <section className={clsx("assistant-activity", `assistant-activity--${run.status}`)}>
      <button
        aria-label="Open activity for this response"
        className="assistant-activity__summary"
        onClick={onOpen}
        type="button"
      >
        <RunStatusIcon status={run.status} />
        <span aria-live="polite" className="assistant-activity__summary-label">
          {summaryLabel(run, isStreaming)}
        </span>
        <span aria-hidden="true" className="assistant-activity__open-indicator">Activity</span>
      </button>
    </section>
  );
});

interface AgentActivityPanelProps {
  message?: ChatMessage;
  isStreaming: boolean;
  onClose: () => void;
  sourceFocus?: SourceFocus;
}

export const AgentActivityPanel = memo(function AgentActivityPanel({
  message,
  isStreaming,
  onClose,
  sourceFocus,
}: AgentActivityPanelProps) {
  const run = useMemo(
    () => AgentActivityMapper.fromParts(message?.parts ?? [], isStreaming),
    [message?.parts, isStreaming],
  );
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | null>(null);

  useEffect(() => {
    if (!message || !sourceFocus) return;
    setHighlightedSourceId(sourceFocus.sourceId);
    const frame = requestAnimationFrame(() => {
      document
        .getElementById(sourceElementId(message.id, sourceFocus.sourceId))
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    const timeout = window.setTimeout(() => setHighlightedSourceId(null), 1_500);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
    };
  }, [message?.id, sourceFocus]);

  return (
    <aside aria-label="Agent activity" className="activity-panel">
      <header className="activity-panel__header">
        <div className="activity-panel__title">
          <h2>Activity</h2>
          <span aria-live="polite" className={`activity-panel__status activity-panel__status--${run.status}`}>
            <RunStatusIcon status={run.status} />
            {panelStatusLabel(run)}
          </span>
        </div>
        <button aria-label="Close activity" className="activity-panel__close" onClick={onClose} type="button">
          <X aria-hidden="true" size={17} />
        </button>
      </header>
      <div className="activity-panel__scroll">
        {message && run.hasActivity ? (
          <>
            <RunSummary run={run} />
            <ActivitySteps messageId={message.id} steps={run.steps} />
            <SourceList
              highlightedSourceId={highlightedSourceId}
              messageId={message.id}
              onHighlight={setHighlightedSourceId}
              sources={run.sources}
            />
          </>
        ) : (
          <p className="activity-panel__empty">Select an assistant response to inspect its activity.</p>
        )}
      </div>
    </aside>
  );
});

function RunSummary({ run }: { run: ReturnType<typeof AgentActivityMapper.fromParts> }) {
  const metrics = [
    run.toolCallCount !== undefined
      ? `${run.toolCallCount} tool${run.toolCallCount === 1 ? "" : "s"}`
      : undefined,
    run.sourceCount > 0 ? `${run.sourceCount} sources found` : undefined,
    run.usedSourceCount > 0 ? `${run.usedSourceCount} sources used` : undefined,
  ].filter(Boolean);
  return (
    <section className="activity-panel__summary" aria-label="Run summary">
      <strong>{panelStatusLabel(run)}</strong>
      {metrics.length > 0 && <p>{metrics.join(" · ")}</p>}
    </section>
  );
}

function ActivitySteps({ messageId, steps }: { messageId: string; steps: ActivityEntry[] }) {
  if (steps.length === 0) return null;
  return (
    <ol aria-label="Agent activity" className="assistant-activity__steps">
      {steps.map((step) => (
        <li
          className={clsx("assistant-activity__step", `assistant-activity__step--${step.status}`)}
          key={`${messageId}:${step.id}`}
        >
          <span aria-label={statusLabel(step.status)} className="assistant-activity__step-icon" role="img">
            <StepIcon step={step} />
          </span>
          <span className="assistant-activity__step-body">
            <span className="assistant-activity__step-heading">
              <span>{step.label}</span>
              {step.durationMs !== undefined && <small>{formatDuration(step.durationMs)}</small>}
            </span>
            {step.resultCount !== undefined && (
              <span className="assistant-activity__result">
                {step.resultCount} source{step.resultCount === 1 ? "" : "s"} found
              </span>
            )}
            {step.description && step.status === "failed" && (
              <span className="assistant-activity__error">{step.description}</span>
            )}
            {step.description && step.status !== "failed" && step.resultCount === undefined && (
              <span className="assistant-activity__description">{step.description}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

function SourceList({
  highlightedSourceId,
  messageId,
  onHighlight,
  sources,
}: {
  highlightedSourceId: string | null;
  messageId: string;
  onHighlight: (sourceId: string) => void;
  sources: SourceResult[];
}) {
  if (sources.length === 0) return null;
  const orderedSources = [...sources].sort(
    (left, right) => Number(right.status === "Used") - Number(left.status === "Used"),
  );

  return (
    <section aria-label={`${sources.length} retrieved sources`} className="assistant-sources">
      <h3>Sources · {sources.length}</h3>
      <div className="assistant-sources__list">
        {orderedSources.map((source) => (
          <SourceItem
            highlighted={source.id === highlightedSourceId}
            key={`${messageId}:${source.id}`}
            messageId={messageId}
            onHighlight={onHighlight}
            source={source}
          />
        ))}
      </div>
    </section>
  );
}

function SourceItem({
  highlighted,
  messageId,
  onHighlight,
  source,
}: {
  highlighted: boolean;
  messageId: string;
  onHighlight: (sourceId: string) => void;
  source: SourceResult;
}) {
  const Icon = sourceIcon(source.type);
  const metadata = [source.provider, source.fileType]
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .join(" · ");
  const content = (
    <>
      <span aria-hidden="true" className="assistant-source__icon"><Icon size={14} /></span>
      <span className="assistant-source__body">
        <span className="assistant-source__title" title={source.title}>{source.title}</span>
        {metadata && <span className="assistant-source__meta">{metadata}</span>}
      </span>
      <span className={clsx("assistant-source__usage", source.status === "Used" && "assistant-source__usage--used")}>
        {source.status === "Used" ? "Used in answer" : source.status === "Restricted" ? "Restricted" : "Found"}
      </span>
      {source.url && <ExternalLink aria-hidden="true" className="assistant-source__open" size={13} />}
    </>
  );
  const className = clsx("assistant-source", highlighted && "assistant-source--highlighted");
  const id = sourceElementId(messageId, source.id);

  if (source.url) {
    return (
      <a
        className={className}
        href={source.url}
        id={id}
        onClick={() => onHighlight(source.id)}
        rel="noopener noreferrer"
        target="_blank"
      >
        {content}
      </a>
    );
  }

  return (
    <button className={className} id={id} onClick={() => onHighlight(source.id)} type="button">
      {content}
    </button>
  );
}

function RunStatusIcon({ status }: { status: AgentRunStatus }) {
  if (status === "completed") {
    return <Check aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
  }
  if (status === "running") {
    return <LoaderCircle aria-hidden="true" className="assistant-activity__status-icon assistant-activity__spin" size={14} />;
  }
  if (status === "failed") {
    return <AlertCircle aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
  }
  if (status === "cancelled") {
    return <CircleStop aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
  }
  return <Clock3 aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
}

function StepIcon({ step }: { step: ActivityEntry }) {
  if (step.status === "running") return <LoaderCircle aria-hidden="true" className="assistant-activity__spin" size={13} />;
  if (step.status === "failed") return <AlertCircle aria-hidden="true" size={13} />;
  if (step.status === "completed") return <Check aria-hidden="true" size={13} />;
  if (step.status === "skipped") return <CircleStop aria-hidden="true" size={13} />;
  if (step.type === "knowledge_retrieval") return <Search aria-hidden="true" size={13} />;
  if (step.type === "tool_execution") return <Wrench aria-hidden="true" size={13} />;
  return <Sparkles aria-hidden="true" size={13} />;
}

function summaryLabel(
  run: ReturnType<typeof AgentActivityMapper.fromParts>,
  isStreaming: boolean,
) {
  if (run.status === "running" || isStreaming) {
    const active = [...run.steps].reverse().find((step) => step.status === "running");
    if (active?.type === "knowledge_retrieval") return "Searching knowledge base…";
    if (active?.type === "next_step_generation") return "Determining next step…";
    if (active?.type === "final_response_generation") return "Generating final response…";
    if (active?.type === "tool_execution") return `${active.label}…`;
    return "Preparing response…";
  }
  if (run.status === "failed") return "Could not complete activity · View details";
  if (run.status === "cancelled") return "Run cancelled · View activity";
  const duration = run.durationMs === undefined ? undefined : formatDuration(run.durationMs);
  if (run.sourceCount > 0) {
    return `Searched ${run.sourceCount} source${run.sourceCount === 1 ? "" : "s"}${duration ? ` · ${duration}` : ""}`;
  }
  return duration ? `Completed in ${duration}` : "View activity";
}

function panelStatusLabel(run: ReturnType<typeof AgentActivityMapper.fromParts>) {
  if (run.status === "running") return "Running";
  if (run.status === "failed") return "Failed";
  if (run.status === "cancelled") return "Cancelled";
  if (run.status === "completed" && run.durationMs !== undefined) {
    return `Completed in ${formatDuration(run.durationMs)}`;
  }
  if (run.status === "completed") return "Completed";
  return "Waiting";
}

function statusLabel(status: ActivityEntry["status"]) {
  if (status === "running") return "Running";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "skipped") return "Skipped";
  return "Pending";
}

function sourceIcon(type: SourceType) {
  if (type === "confluence") return BookOpen;
  if (type === "database") return Database;
  if (type === "excel" || type === "csv" || type === "google-sheets") return FileSpreadsheet;
  if (type === "pdf" || type === "word" || type === "document") return FileText;
  return FileType;
}

function sourceElementId(messageId: string, sourceId: string) {
  return `message-source-${encodeURIComponent(messageId)}-${encodeURIComponent(sourceId)}`;
}

function formatDuration(durationMs: number) {
  if (durationMs < 10_000) return `${(durationMs / 1_000).toFixed(1)}s`;
  return `${Math.round(durationMs / 1_000)}s`;
}
