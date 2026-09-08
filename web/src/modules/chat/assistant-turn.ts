import {
  isFunctionCallItem,
  isMessageItem,
  isOutputTextPart,
  orderedTurnItems,
} from "./message-stream.ts";
import type { TurnState } from "./types";

export type AssistantTurnItem =
  | { kind: "message"; id: string; text: string; state: "streaming" | "done" }
  | {
      kind: "tool";
      id: string;
      name: string;
      state: "active" | "completed" | "error";
    }
  | { kind: "reasoning"; id: string; text: string; state: "active" | "completed" };

/**
 * The provider-hosted tools, mapped to the activity name the UI speaks.
 *
 * These arrive as output items rather than function calls, because the model's
 * provider runs them itself. The backend narrows each one to its type and
 * status before it reaches here, so this is the whole vocabulary.
 */
const HOSTED_TOOL_ACTIVITIES: Record<string, string> = {
  code_interpreter_call: "code_interpreter",
  shell_call: "shell",
};

/**
 * Presentation data derived from materialized output items. The reducer owns
 * ordering and state; this function only chooses how each semantic item reads.
 */
export function assistantTurnItems(turn: TurnState | undefined): AssistantTurnItem[] {
  if (!turn) return [];
  const newestResponseIndex = turn.responseOrder.length - 1;
  const items: AssistantTurnItem[] = [];

  for (const ordered of orderedTurnItems(turn)) {
    const { id, item } = ordered;
    if (isMessageItem(item) && item.role === "assistant") {
      const text = item.content
        .filter(isOutputTextPart)
        .map((part) => part.text)
        .join("");
      if (text) {
        items.push({
          kind: "message",
          id,
          text,
          state: item.status === "completed" || turn.status !== "streaming"
            ? "done"
            : "streaming",
        });
      }
      continue;
    }

    if (isFunctionCallItem(item)) {
      items.push({
        kind: "tool",
        id,
        name: item.name,
        state: toolState(turn, ordered.responseIndex, newestResponseIndex),
      });
      continue;
    }

    const hosted = HOSTED_TOOL_ACTIVITIES[item.type];
    if (hosted) {
      items.push({
        kind: "tool",
        id,
        name: hosted,
        // A hosted call completes inside its own response, so its item status
        // is the whole truth about it — unlike a function call, which the
        // agent executes after the response that requested it settled.
        state: hostedToolState(turn, item.status, ordered.responseIndex, newestResponseIndex),
      });
      continue;
    }

    if (item.type === "reasoning" && Array.isArray(item.summary)) {
      const text = item.summary
        .filter((part): part is { type: "summary_text"; text: string } => (
          typeof part?.text === "string"
        ))
        .map((part) => part.text)
        .join("");
      const active = turn.status === "streaming"
        && ordered.responseIndex === newestResponseIndex
        && item.status !== "completed";
      if (text || active) {
        items.push({ kind: "reasoning", id, text, state: active ? "active" : "completed" });
      }
    }
  }
  return items;
}

function hostedToolState(
  turn: TurnState,
  status: string | undefined,
  responseIndex: number,
  newestResponseIndex: number,
): "active" | "completed" | "error" {
  if (status === "completed") return "completed";
  if (status === "failed" || status === "incomplete") return "error";
  if (turn.status === "failed" && responseIndex === newestResponseIndex) return "error";
  if (turn.status === "streaming") return "active";
  return "completed";
}

function toolState(
  turn: TurnState,
  responseIndex: number,
  newestResponseIndex: number,
): "active" | "completed" | "error" {
  if (turn.status === "failed" && responseIndex === newestResponseIndex) return "error";
  // A function-call item's own lifecycle only says its arguments finished
  // streaming. It remains visible as active until a later response begins,
  // which is the semantic indication that the function execution returned.
  if (turn.status === "streaming" && responseIndex === newestResponseIndex) return "active";
  return "completed";
}
