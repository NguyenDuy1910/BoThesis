"use client";

import clsx from "clsx";
import { AlertCircle, Check, FileSearch, LoaderCircle, Search, Wrench } from "lucide-react";
import { memo } from "react";

import { assistantTurnItems, type AssistantTurnItem } from "../assistant-turn";
import type { AgentItemStore, ChatMessagePart } from "../types";
import { IncrementalMarkdown } from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  isStreaming,
  onRevealingChange,
  parts,
  runtime,
}: {
  isStreaming: boolean;
  /** Report while the turn's newest text is still easing onto screen. */
  onRevealingChange?: (isRevealing: boolean) => void;
  parts: ChatMessagePart[];
  runtime?: AgentItemStore;
}) {
  const items = assistantTurnItems(parts, isStreaming, runtime);
  const lastItem = items.at(-1);
  // One busy signal at a time: the dots stand in for text that has not started
  // yet. Once any text is streaming, the text itself is the progress indicator.
  const showPending = isStreaming && (!lastItem || lastItem.kind === "tool");
  // Only the newest text block can still be revealing once the stream ends;
  // earlier blocks drained while the turn was still running.
  const revealingItemId = items.filter((item) => item.kind !== "tool").at(-1)?.id;

  if (!items.length && !showPending) return null;

  return (
    <div className="assistant-turn">
      {items.map((item) => {
        if (item.kind === "message") {
          return (
            <div className="assistant-content assistant-turn__message" key={item.id}>
              <IncrementalMarkdown
                isStreaming={isStreaming && item.state === "streaming"}
                onRevealingChange={item.id === revealingItemId ? onRevealingChange : undefined}
                text={item.text}
              />
            </div>
          );
        }
        if (item.kind === "tool") {
          return <InlineToolActivity item={item} key={item.id} />;
        }
        return (
          <div className="assistant-content assistant-turn__response" key={item.id}>
            <div className="answer-detail">
              <IncrementalMarkdown
                isStreaming={isStreaming && item.state === "streaming"}
                onRevealingChange={item.id === revealingItemId ? onRevealingChange : undefined}
                text={item.text}
              />
            </div>
          </div>
        );
      })}
      {showPending && (
        <span aria-label="Assistant is working" className="assistant-turn__pending" role="status">
          <span />
          <span />
          <span />
        </span>
      )}
    </div>
  );
});

function InlineToolActivity({ item }: { item: Extract<AssistantTurnItem, { kind: "tool" }> }) {
  const Icon = item.state === "active"
    ? LoaderCircle
    : item.state === "completed"
      ? Check
      : item.state === "error"
        ? AlertCircle
        : item.category === "retrieval"
          ? Search
          : item.category === "document"
            ? FileSearch
            : Wrench;
  const measure = toolMeasure(item);

  return (
    <div
      aria-label={`${item.label}: ${item.state}`}
      className={clsx(
        "assistant-turn__tool",
        `assistant-turn__tool--${item.state}`,
      )}
      role="status"
    >
      <Icon aria-hidden="true" className="assistant-turn__tool-icon" size={13} />
      <span className="assistant-turn__tool-body">
        <span className="assistant-turn__tool-label">{toolLabel(item)}</span>
        {measure && <span className="assistant-turn__tool-count">{measure}</span>}
        {item.detail && (
          <span className="assistant-turn__tool-detail">{item.detail}</span>
        )}
      </span>
    </div>
  );
}

/** Compact evidence that work happened: results found, and time only when slow. */
function toolMeasure(item: Extract<AssistantTurnItem, { kind: "tool" }>) {
  if (item.state === "active") return undefined;
  const parts: string[] = [];
  if (typeof item.resultCount === "number" && item.resultCount >= 0) {
    parts.push(`${item.resultCount} ${item.resultCount === 1 ? "result" : "results"}`);
  }
  if (typeof item.durationMs === "number" && item.durationMs >= 1000) {
    parts.push(`${(item.durationMs / 1000).toFixed(1)}s`);
  }
  return parts.length ? parts.join(" · ") : undefined;
}

function toolLabel(item: Extract<AssistantTurnItem, { kind: "tool" }>) {
  if (item.category === "retrieval") {
    if (item.state === "active") return "Searching knowledge…";
    if (item.state === "completed") return "Searched knowledge";
    if (item.state === "error") return "Couldn't search knowledge";
    return "Knowledge search skipped";
  }
  if (item.category === "document") {
    if (item.state === "active") return "Reading document…";
    if (item.state === "completed") return "Read document";
    return item.label;
  }
  if (item.state === "active") return "Running tool…";
  return item.state === "completed" ? `Ran ${item.label}` : item.label;
}
