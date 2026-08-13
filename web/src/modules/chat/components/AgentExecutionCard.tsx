"use client";

import clsx from "clsx";
import {
  AlertCircle,
  BookOpen,
  CircleStop,
  Database,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  FileType,
  LoaderCircle,
  X,
} from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";

import { AgentActivityMapper } from "@/modules/chat/activity-mapper";
import type {
  ActivityEntry,
  AgentRunStatus,
  SourceResult,
  SourceType,
} from "@/modules/chat/activity";
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
  const hasAnswer = message.parts.some((part) => part.type === "text" && part.text.length > 0);

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
          {summaryLabel(run, isStreaming, hasAnswer)}
        </span>
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
  const [view, setView] = useState<"activity" | "sources">(
    sourceFocus ? "sources" : "activity",
  );

  useEffect(() => {
    if (!message || !sourceFocus) return;
    setView("sources");
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
    <aside aria-label="Response details" className="activity-panel">
      <header className="activity-panel__header">
        <div className="activity-panel__title">
          <h2>Details</h2>
        </div>
        <button aria-label="Close details" className="activity-panel__close" onClick={onClose} type="button">
          <X aria-hidden="true" size={17} />
        </button>
      </header>
      <nav aria-label="Response details" className="activity-panel__tabs">
        <button
          aria-current={view === "activity" ? "page" : undefined}
          onClick={() => setView("activity")}
          type="button"
        >
          Activity
        </button>
        <button
          aria-current={view === "sources" ? "page" : undefined}
          onClick={() => setView("sources")}
          type="button"
        >
          Sources
        </button>
      </nav>
      <div className="activity-panel__scroll">
        {message && run.hasActivity ? (
          view === "activity" ? (
            <ActivitySteps messageId={message.id} steps={run.steps} />
          ) : (
            <SourceList
              highlightedSourceId={highlightedSourceId}
              messageId={message.id}
              onHighlight={setHighlightedSourceId}
              sources={run.sources}
            />
          )
        ) : (
          <p className="activity-panel__empty">Select an assistant response to inspect its activity.</p>
        )}
      </div>
    </aside>
  );
});

function ActivitySteps({ messageId, steps }: { messageId: string; steps: ActivityEntry[] }) {
  const visibleSteps = minimalActivitySteps(steps);
  if (visibleSteps.length === 0) return null;
  return (
    <ol aria-label="Agent activity" className="assistant-activity__steps">
      {visibleSteps.map((step) => {
        const hasStatusIcon = step.status === "running"
          || step.status === "failed"
          || step.status === "skipped";
        return (
          <li
            className={clsx(
              "assistant-activity__step",
              `assistant-activity__step--${step.status}`,
              !hasStatusIcon && "assistant-activity__step--text-only",
            )}
            key={`${messageId}:${step.id}`}
          >
            {hasStatusIcon && (
              <span aria-label={statusLabel(step.status)} className="assistant-activity__step-icon" role="img">
                <StepIcon step={step} />
              </span>
            )}
            <span className="assistant-activity__step-body">
              <span className="assistant-activity__step-heading">
                <span>{step.label}</span>
              </span>
              {step.description && step.status === "failed" && (
                <span className="assistant-activity__error">{step.description}</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function minimalActivitySteps(steps: ActivityEntry[]): ActivityEntry[] {
  const attachmentSteps = steps.filter((step) => step.type === "document_preparation");
  const retrievalSteps = steps.filter((step) => step.type === "knowledge_retrieval");
  const toolSteps = steps.filter((step) => step.type === "tool_execution");
  const generationStep = [...steps]
    .reverse()
    .find((step) => step.type === "final_response_generation");
  const visibleSteps: ActivityEntry[] = [];

  visibleSteps.push(...attachmentSteps.map((step) => ({
    ...step,
    durationMs: undefined,
    resultCount: undefined,
    description: step.status === "failed" ? step.description : undefined,
  })));

  if (retrievalSteps.length > 0) {
    visibleSteps.push({
      ...retrievalSteps[0],
      id: "knowledge-retrieval",
      label: "Search knowledge base",
      status: aggregateStepStatus(retrievalSteps),
      description: retrievalSteps.find((step) => step.status === "failed")?.description,
      durationMs: undefined,
      resultCount: undefined,
    });
  }

  visibleSteps.push(...toolSteps.map((step) => ({
    ...step,
    durationMs: undefined,
    resultCount: undefined,
    description: step.status === "failed" ? step.description : undefined,
  })));

  if (generationStep) {
    visibleSteps.push({
      ...generationStep,
      id: "response-generation",
      label: "Generate response",
      durationMs: undefined,
      resultCount: undefined,
      description: generationStep.status === "failed"
        ? generationStep.description
        : undefined,
    });
  }

  return visibleSteps;
}

function aggregateStepStatus(steps: ActivityEntry[]): ActivityEntry["status"] {
  if (steps.some((step) => step.status === "failed")) return "failed";
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.some((step) => step.status === "pending")) return "pending";
  if (steps.every((step) => step.status === "skipped")) return "skipped";
  return "completed";
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
  if (sources.length === 0) {
    return <p className="activity-panel__empty">No sources were used for this response.</p>;
  }
  const orderedSources = [...sources].sort(
    (left, right) => Number(right.status === "Used") - Number(left.status === "Used"),
  );

  return (
    <section aria-label={`${sources.length} retrieved sources`} className="assistant-sources">
      <h3>Sources</h3>
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
  const metadata = [
    source.provider ?? sourceTypeLabel(source.type),
    source.fileType,
    source.status === "Restricted" ? "Restricted" : undefined,
  ]
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .join(" · ");
  const content = (
    <>
      <span aria-hidden="true" className="assistant-source__icon"><Icon size={16} /></span>
      <span className="assistant-source__body">
        <span className="assistant-source__title" title={source.title}>{source.title}</span>
        {(metadata || source.location) && (
          <span className="assistant-source__meta">
            {[metadata, source.location].filter(Boolean).join(" · ")}
          </span>
        )}
        {source.snippet && <span className="assistant-source__snippet">{source.snippet}</span>}
      </span>
      {source.url && (
        <span className="assistant-source__open">
          Open <ExternalLink aria-hidden="true" size={12} />
        </span>
      )}
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
  if (status === "running") {
    return <LoaderCircle aria-hidden="true" className="assistant-activity__status-icon assistant-activity__spin" size={14} />;
  }
  if (status === "failed") {
    return <AlertCircle aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
  }
  if (status === "cancelled") {
    return <CircleStop aria-hidden="true" className="assistant-activity__status-icon" size={14} />;
  }
  return null;
}

function StepIcon({ step }: { step: ActivityEntry }) {
  if (step.status === "running") return <LoaderCircle aria-hidden="true" className="assistant-activity__spin" size={13} />;
  if (step.status === "failed") return <AlertCircle aria-hidden="true" size={13} />;
  if (step.status === "skipped") return <CircleStop aria-hidden="true" size={13} />;
  return null;
}

function summaryLabel(
  run: ReturnType<typeof AgentActivityMapper.fromParts>,
  isStreaming: boolean,
  hasAnswer: boolean,
) {
  if (run.status === "running" || isStreaming) {
    const active = [...run.steps].reverse().find((step) => step.status === "running");
    if (active?.type === "document_preparation") return "Đang chuẩn bị tài liệu…";
    if (active?.type === "knowledge_retrieval") return "Đang tìm trong Knowledge…";
    if (active?.type === "tool_execution") return "Đang sử dụng công cụ…";
    if (hasAnswer || active?.type === "final_response_generation") {
      return "Đang tổng hợp câu trả lời…";
    }
    return "Đang phân tích…";
  }
  if (run.status === "failed") return "Không thể hoàn tất · Details";
  if (run.status === "cancelled") return "Đã dừng · Details";
  return "Details";
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

function sourceTypeLabel(type: SourceType) {
  if (type === "google-docs") return "Google Docs";
  if (type === "google-sheets") return "Google Sheets";
  if (type === "google-slides") return "Google Slides";
  if (type === "pdf") return "PDF";
  if (type === "word") return "Word";
  if (type === "csv") return "CSV";
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function sourceElementId(messageId: string, sourceId: string) {
  return `message-source-${encodeURIComponent(messageId)}-${encodeURIComponent(sourceId)}`;
}
