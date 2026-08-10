"use client";

import clsx from "clsx";
import {
  AlertCircle,
  BookOpen,
  ChevronDown,
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
} from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

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
  sourceFocus?: SourceFocus;
}

export const AgentExecutionCard = memo(function AgentExecutionCard({
  message,
  isStreaming,
  sourceFocus,
}: AgentExecutionCardProps) {
  const run = useMemo(
    () => AgentActivityMapper.fromParts(message.parts, isStreaming),
    [message.parts, isStreaming],
  );
  const [expanded, setExpanded] = useState(false);
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | null>(null);
  const previousStatusRef = useRef(run.status);
  const detailsId = `assistant-activity-${message.id}`;

  useEffect(() => {
    const previousStatus = previousStatusRef.current;
    if (previousStatus === "running" && run.status !== "running") {
      setExpanded(false);
    }
    previousStatusRef.current = run.status;
  }, [run.status]);

  useEffect(() => {
    if (!sourceFocus) return;
    setExpanded(true);
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
  }, [message.id, sourceFocus]);

  if (!run.hasActivity) return null;

  return (
    <section className={clsx("assistant-activity", `assistant-activity--${run.status}`)}>
      <button
        aria-controls={detailsId}
        aria-expanded={expanded}
        className="assistant-activity__summary"
        onClick={() => setExpanded((current) => !current)}
        type="button"
      >
        <RunStatusIcon status={run.status} />
        <span aria-live="polite" className="assistant-activity__summary-label">
          {summaryLabel(run, isStreaming)}
        </span>
        <ChevronDown
          aria-hidden="true"
          className={clsx("assistant-activity__chevron", expanded && "assistant-activity__chevron--open")}
          size={14}
        />
      </button>

      {expanded && (
        <div className="assistant-activity__details" id={detailsId}>
          <ActivitySteps messageId={message.id} steps={run.steps} />
          <SourceList
            highlightedSourceId={highlightedSourceId}
            messageId={message.id}
            onHighlight={setHighlightedSourceId}
            sources={run.sources}
          />
        </div>
      )}
    </section>
  );
});

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
            {step.query && <span className="assistant-activity__query">“{step.query}”</span>}
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
  if (status === "completed") return null;
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
  if (step.status === "completed") return <span aria-hidden="true" className="assistant-activity__step-dot" />;
  if (step.status === "skipped") return <CircleStop aria-hidden="true" size={13} />;
  if (step.type === "retrieval") return <Search aria-hidden="true" size={13} />;
  if (step.type === "tool") return <Wrench aria-hidden="true" size={13} />;
  return <Sparkles aria-hidden="true" size={13} />;
}

function summaryLabel(
  run: ReturnType<typeof AgentActivityMapper.fromParts>,
  isStreaming: boolean,
) {
  if (run.status === "running" || isStreaming) {
    const active = [...run.steps].reverse().find((step) => step.status === "running");
    if (active?.type === "retrieval") return "Searching knowledge base…";
    if (active?.type === "generation") return "Preparing answer…";
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
