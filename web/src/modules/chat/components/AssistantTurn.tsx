"use client";

import clsx from "clsx";
import {
  Check,
  ChevronRight,
  Database,
  FileSearch,
  LoaderCircle,
  Search,
  Sparkles,
  Terminal,
  Wrench,
} from "lucide-react";
import { memo, useMemo } from "react";

import { assistantTurnItems, type AssistantTurnItem } from "../assistant-turn";
import type { AnswerSource } from "../sources";
import type { TurnState } from "../types";
import {
  CitationRenderingProvider,
  citationRenderingSources,
  IncrementalMarkdown,
} from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  activeCitationId,
  activityConnectorLabel,
  isStreaming,
  onOpenSource,
  onRevealingChange,
  sources,
  turn,
}: {
  activeCitationId?: string;
  activityConnectorLabel?: string;
  isStreaming: boolean;
  onOpenSource?: (source: AnswerSource) => void;
  /** Report while the turn's newest text is still easing onto screen. */
  onRevealingChange?: (isRevealing: boolean) => void;
  /** The citations this answer produced, for the inline chips. */
  sources?: readonly AnswerSource[];
  turn?: TurnState;
}) {
  const items = assistantTurnItems(turn);
  const lastItem = items.at(-1);
  const showPending = isStreaming && !lastItem;
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
        {items.map((item) => {
          if (item.kind === "message") {
            return (
              <div className="assistant-content" key={item.id}>
                <IncrementalMarkdown
                  isStreaming={isStreaming && item.state === "streaming"}
                  onRevealingChange={item.id === revealingItemId ? onRevealingChange : undefined}
                  text={item.text}
                />
              </div>
            );
          }
          if (item.kind === "tool") return <ToolActivity connectorLabel={activityConnectorLabel} item={item} key={item.id} />;
          return <ReasoningActivity item={item} key={item.id} />;
        })}
        {showPending && (
          <span aria-label="Assistant is working" className="assistant-turn__pending" role="status">
            <LoaderCircle aria-hidden="true" className="assistant-turn__tool-icon" size={13} />
            <span>Analyzing…</span>
          </span>
        )}
      </div>
    </CitationRenderingProvider>
  );
});

function ToolActivity({ connectorLabel, item }: { connectorLabel?: string; item: Extract<AssistantTurnItem, { kind: "tool" }> }) {
  const presentation = toolPresentation(item.name, item.state, connectorLabel);
  const Icon = item.state === "active" ? LoaderCircle : presentation.icon;

  return (
    <div
      aria-label={presentation.label}
      className={clsx("assistant-turn__tool", `assistant-turn__tool--${item.state}`)}
      role={item.state === "active" ? "status" : undefined}
    >
      {item.state === "completed" ? (
        <Check aria-hidden="true" className="assistant-turn__tool-icon" size={13} />
      ) : (
        <Icon aria-hidden="true" className="assistant-turn__tool-icon" size={13} />
      )}
      <span className="assistant-turn__tool-label">{presentation.label}</span>
    </div>
  );
}

function ReasoningActivity({ item }: { item: Extract<AssistantTurnItem, { kind: "reasoning" }> }) {
  if (item.state === "active") {
    return (
      <div className="assistant-turn__reasoning" role="status">
        <LoaderCircle aria-hidden="true" className="assistant-turn__tool-icon" size={13} />
        <span>Thinking…</span>
      </div>
    );
  }
  if (!item.text) return null;
  return (
    <details className="assistant-turn__reasoning">
      <summary>
        <ChevronRight aria-hidden="true" className="assistant-turn__reasoning-caret" size={13} />
        <span>Thought process</span>
      </summary>
      <div className="assistant-turn__reasoning-summary">{item.text}</div>
    </details>
  );
}

function toolPresentation(
  name: string,
  state: Extract<AssistantTurnItem, { kind: "tool" }> ["state"],
  connectorLabel?: string,
) {
  const completed = state === "completed";
  if (name === "knowledge_search") {
    return {
      label: state === "error"
        ? "Knowledge search could not complete"
        : completed
          ? `Searched ${connectorLabel ?? "knowledge"}`
          : `Searching ${connectorLabel ?? "knowledge"}…`,
      icon: Search,
    };
  }
  if (name === "sql_query") {
    return {
      label: state === "error"
        ? "Data query could not complete"
        : completed ? "Queried data" : "Querying data…",
      icon: Database,
    };
  }
  if (name === "open_document") {
    return {
      label: state === "error"
        ? "Document could not be opened"
        : completed ? "Read the document" : "Reading the document…",
      icon: FileSearch,
    };
  }
  // The native execution tools stay semantic: a user is told what is being
  // done to their files, never which runtime did it.
  if (name === "code_interpreter") {
    return {
      label: state === "error"
        ? "Preparing the file could not complete"
        : completed ? "Prepared the file" : "Preparing the file…",
      icon: Sparkles,
    };
  }
  if (name === "shell") {
    return {
      label: state === "error"
        ? "Converting the file could not complete"
        : completed ? "Converted the file" : "Converting the file…",
      icon: Terminal,
    };
  }
  if (state === "error") return { label: "Tool could not complete", icon: Wrench };
  return { label: completed ? "Completed tool activity" : "Running tool…", icon: Wrench };
}
