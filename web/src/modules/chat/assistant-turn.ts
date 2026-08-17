import type { ChatMessagePart } from "./types";

export type AssistantTurnItem =
  | {
      kind: "interim";
      id: string;
      text: string;
    }
  | {
      kind: "tool";
      id: string;
      label: string;
      detail?: string;
      category: "document" | "retrieval" | "tool";
      state: "active" | "completed" | "error" | "skipped";
    }
  | {
      kind: "response";
      id: string;
      text: string;
      state: "streaming" | "done";
    };

export function assistantTurnItems(parts: ChatMessagePart[]): AssistantTurnItem[] {
  const items: AssistantTurnItem[] = [];

  for (const [index, part] of parts.entries()) {
    if (part.type === "data-reasoning") {
      const text = part.data.text.trim();
      if (text) {
        items.push({
          kind: "interim",
          id: part.id ?? `interim-${part.data.source}-${part.data.turn}`,
          text,
        });
      }
      continue;
    }

    if (part.type === "data-status") {
      const category = inlineToolCategory(part);
      if (!category) continue;
      items.push({
        kind: "tool",
        id: part.data.stepId ?? part.id ?? `tool-${index}`,
        label: cleanActivityLabel(part.data.label, part.data.toolName),
        detail: part.data.detail?.trim() || undefined,
        category,
        state: part.data.state,
      });
      continue;
    }

    if (part.type === "text" && part.text) {
      items.push({
        kind: "response",
        id: `response-${index}`,
        text: part.text,
        state: part.state,
      });
    }
  }

  return items;
}

function inlineToolCategory(
  part: Extract<ChatMessagePart, { type: "data-status" }>,
): "document" | "retrieval" | "tool" | undefined {
  if (part.data.phase === "document" || part.data.activityType === "document_preparation") {
    return "document";
  }
  if (part.data.phase === "retrieval" || part.data.activityType === "knowledge_retrieval") {
    return "retrieval";
  }
  if (part.data.phase === "tool" || part.data.activityType === "tool_execution") {
    return "tool";
  }
  return undefined;
}

function cleanActivityLabel(label: string, toolName: string | undefined) {
  const cleanLabel = label
    .replace(/^(?:Act|Observe)\s*[·:]\s*/i, "")
    .trim();
  if (cleanLabel && !/^(?:Think|Final response)$/i.test(cleanLabel)) {
    return cleanLabel;
  }
  if (!toolName) return "Using tool";
  return toolName
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
