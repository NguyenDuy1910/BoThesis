"use client";

import clsx from "clsx";
import { AlertCircle, Check, FileSearch, LoaderCircle, Search, Wrench } from "lucide-react";
import { memo } from "react";

import { assistantTurnItems, type AssistantTurnItem } from "../assistant-turn";
import type { AgentItemStore, ChatMessagePart } from "../types";
import { IncrementalMarkdown } from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  isStreaming,
  parts,
  runtime,
}: {
  isStreaming: boolean;
  parts: ChatMessagePart[];
  runtime?: AgentItemStore;
}) {
  const items = assistantTurnItems(parts, isStreaming, runtime);
  const lastItem = items.at(-1);
  const showPending = isStreaming && (!lastItem || lastItem.kind === "tool");

  if (!items.length && !showPending) return null;

  return (
    <div className="assistant-turn">
      {items.map((item, index) => {
        if (item.kind === "message") {
          return (
            <div className="assistant-content assistant-turn__message" key={item.id}>
              <IncrementalMarkdown
                isStreaming={isStreaming && item.state === "streaming"}
                text={item.text}
              />
            </div>
          );
        }
        if (item.kind === "tool") {
          return <InlineToolActivity item={item} key={item.id} />;
        }
        const isLastResponse = !items
          .slice(index + 1)
          .some((candidate) => candidate.kind === "response");
        return (
          <div className="assistant-content assistant-turn__response" key={item.id}>
            <div className="answer-detail">
              <IncrementalMarkdown
                isStreaming={isStreaming && item.state === "streaming"}
                text={item.text}
              />
            </div>
            {isStreaming && item.state === "streaming" && isLastResponse && (
              <span className="streaming-cursor" />
            )}
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
        {item.category === "retrieval" && item.count > 1 && (
          <span className="assistant-turn__tool-count">{item.count} searches</span>
        )}
        {item.detail && (
          <span className="assistant-turn__tool-detail">{item.detail}</span>
        )}
      </span>
    </div>
  );
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
