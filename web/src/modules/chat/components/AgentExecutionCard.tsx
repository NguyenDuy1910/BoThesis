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
  SourceResult,
  SourceType,
} from "@/modules/chat/activity";
import type { ChatMessage } from "@/modules/chat/types";

interface SourceFocus {
  sourceId: string;
  nonce: number;
}

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
              {step.description && (
                <span className={step.status === "failed"
                  ? "assistant-activity__error"
                  : "assistant-activity__detail"}
                >
                  {step.description}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function minimalActivitySteps(steps: ActivityEntry[]): ActivityEntry[] {
  return steps
    .filter((step) => step.type !== "final_response_generation")
    .map((step) => ({
      ...step,
      durationMs: undefined,
      resultCount: undefined,
    }));
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

function StepIcon({ step }: { step: ActivityEntry }) {
  if (step.status === "running") return <LoaderCircle aria-hidden="true" className="assistant-activity__spin" size={13} />;
  if (step.status === "failed") return <AlertCircle aria-hidden="true" size={13} />;
  if (step.status === "skipped") return <CircleStop aria-hidden="true" size={13} />;
  return null;
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
