"use client";

import clsx from "clsx";
import { FileSearch, Search, Wrench } from "lucide-react";
import { memo, type MouseEventHandler } from "react";

import { assistantTurnItems, type AssistantTurnItem } from "../assistant-turn";
import type { ChatMessagePart } from "../types";
import { IncrementalMarkdown } from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  isStreaming,
  onCitationClick,
  parts,
}: {
  isStreaming: boolean;
  onCitationClick: MouseEventHandler<HTMLDivElement>;
  parts: ChatMessagePart[];
}) {
  const items = assistantTurnItems(parts);
  const lastItem = items.at(-1);
  const showPending = isStreaming && (
    !lastItem
    || lastItem.kind === "interim"
    || (lastItem.kind === "tool" && lastItem.state !== "active")
  );

  if (!items.length && !showPending) return null;

  return (
    <div className="assistant-turn" onClick={onCitationClick}>
      {items.map((item, index) => {
        if (item.kind === "interim") {
          return (
            <p aria-live="polite" className="assistant-turn__interim" key={item.id}>
              {item.text}
            </p>
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
  const Icon = item.category === "retrieval"
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
    >
      <Icon aria-hidden="true" className="assistant-turn__tool-icon" size={14} />
      <span className="assistant-turn__tool-body">
        <span className="assistant-turn__tool-label">{item.label}</span>
        {item.detail && (
          <span className="assistant-turn__tool-detail">{item.detail}</span>
        )}
      </span>
    </div>
  );
}
