import {
  isHostedExecutionCallItem,
  isHostedExecutionResultItem,
  isFunctionCallItem,
  isMessageItem,
  isOutputTextPart,
  orderedTurnItems,
} from "./message-stream.ts";
import type { HostedExecutionOutput, RuntimeActivity, TurnState } from "./types";

export type AssistantTurnItem =
  | {
      kind: "message";
      id: string;
      phase: "commentary" | "final_answer";
      text: string;
      state: "streaming" | "done";
    }
  | { kind: "activity"; id: string; activity: RuntimeActivity }
  | {
      kind: "execution";
      id: string;
      callId: string;
      state: "running" | "completed" | "failed" | "timeout";
      commands: string[];
      output: HostedExecutionOutput[];
      files: string[];
    };

export type AssistantTurnRenderableItem = Exclude<AssistantTurnItem, { kind: "activity" }>
  | {
      kind: "activity_group";
      id: string;
      activities: RuntimeActivity[];
    };

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
      continue;
    }

    if (isHostedExecutionCallItem(item)) {
      items.push({
        kind: "execution",
        id,
        callId: item.call_id,
        state: "running",
        commands: item.commands,
        output: [],
        files: [],
      });
      continue;
    }

    if (isHostedExecutionResultItem(item)) {
      const timedOut = item.output.some((entry) => entry.timed_out);
      const failed = item.output.some(
        (entry) => !entry.timed_out && entry.exit_code !== 0,
      );
      items.push({
        kind: "execution",
        id,
        callId: item.call_id,
        state: timedOut ? "timeout" : failed ? "failed" : "completed",
        commands: item.commands,
        output: item.output,
        files: item.workspace_files?.filter((file) => typeof file === "string") ?? [],
      });
    }
  }
  for (const activity of turn.runtimeActivities ?? []) {
    if (!seenActivities.has(activity.callId)) {
      items.push({ kind: "activity", id: activity.callId, activity });
    }
  }
  return items;
}

/**
 * A turn owns one activity surface. Runtime actions can be interleaved with
 * commentary or later answer text, but rendering each contiguous run as a
 * separate card turns the conversation into an event log. The first observed
 * action fixes the surface's place in the transcript; subsequent actions
 * update that same surface in place.
 */
export function groupAssistantTurnItems(
  items: AssistantTurnItem[],
): AssistantTurnRenderableItem[] {
  const grouped: AssistantTurnRenderableItem[] = [];
  const activities = items.flatMap((item) => item.kind === "activity" ? [item.activity] : []);
  let insertedActivitySurface = false;

  for (const item of items) {
    if (item.kind === "activity") {
      if (insertedActivitySurface) continue;
      insertedActivitySurface = true;
      grouped.push({
        kind: "activity_group",
        id: `activities:${item.id}`,
        activities,
      });
      continue;
    }
    grouped.push(item);
  }
  return grouped;
}
