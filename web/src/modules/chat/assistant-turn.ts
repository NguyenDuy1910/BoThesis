import {
  isFunctionCallItem,
  isMessageItem,
  isOutputTextPart,
  orderedTurnItems,
} from "./message-stream.ts";
import type { RuntimeActivity, TurnState } from "./types";

export type AssistantTurnItem =
  | {
      kind: "message";
      id: string;
      phase: "commentary" | "final_answer";
      text: string;
      state: "streaming" | "done";
    }
  | { kind: "activity"; id: string; activity: RuntimeActivity };

/**
 * Function calls are model intent, not user-visible activity. An activity
 * appears only after the runtime says that call actually began executing.
 */
export function assistantTurnItems(turn: TurnState | undefined): AssistantTurnItem[] {
  if (!turn) return [];
  const activities = new Map(
    (turn.runtimeActivities ?? []).map((activity) => [activity.callId, activity]),
  );
  const seenActivities = new Set<string>();
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
          phase: item.phase === "commentary" ? "commentary" : "final_answer",
          text,
          state: item.status === "completed" || turn.status !== "streaming"
            ? "done"
            : "streaming",
        });
      }
      continue;
    }

    if (isFunctionCallItem(item)) {
      const activity = activities.get(item.call_id);
      if (activity) {
        items.push({ kind: "activity", id: item.call_id, activity });
        seenActivities.add(item.call_id);
      }
    }
  }
  for (const activity of turn.runtimeActivities ?? []) {
    if (!seenActivities.has(activity.callId)) {
      items.push({ kind: "activity", id: activity.callId, activity });
    }
  }
  return items;
}
