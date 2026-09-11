import type { TurnState } from "./types";
import { isMessageItem, isOutputTextPart } from "./message-stream.ts";

export type RecoveryVariant =
  | "model_unavailable"
  | "knowledge_unavailable"
  | "tool_failed"
  | "stream_interrupted";

export interface TurnRecovery {
  variant: RecoveryVariant;
  title: string;
  detail: string;
  retryLabel: string;
}

/**
 * Translate only the runtime facts we have into an honest local recovery.
 * The protocol has no approval or resumable-session event, so neither is
 * implied here.
 */
export function recoveryForTurn(turn: TurnState | undefined): TurnRecovery | null {
  const error = turn?.error?.trim();
  if (!error || error === "Response stopped.") return null;

  const failedActivities = (turn?.runtimeActivities ?? []).filter((activity) => (
    activity.state === "failed" || activity.state === "timeout"
  ));
  if (failedActivities.some((activity) => activity.toolName === "knowledge_search")) {
    return {
      variant: "knowledge_unavailable",
      title: "Company knowledge is temporarily unavailable",
      detail: "I couldn’t reach company knowledge, so I won’t invent an enterprise answer.",
      retryLabel: "Retry search",
    };
  }
  if (failedActivities.length) {
    return {
      variant: "tool_failed",
      title: "An action could not be completed",
      detail: "The conversation and completed work are preserved. Retry the turn or adjust your request.",
      retryLabel: "Retry",
    };
  }

  const lowerError = error.toLowerCase();
  const hasPartialTurn = Boolean((turn?.runtimeActivities?.length ?? 0) || hasVisibleOutput(turn));
  if (hasPartialTurn || /interrupted|disconnect|network|connection/.test(lowerError)) {
    return {
      variant: "stream_interrupted",
      title: "Response interrupted",
      detail: "Retrieved sources and any partial output remain visible. Start the turn again when you’re ready.",
      retryLabel: "Start again",
    };
  }
  return {
    variant: "model_unavailable",
    title: "Service temporarily unavailable",
    detail: "Your message is safe. No tool or external action was started.",
    retryLabel: "Retry",
  };
}

function hasVisibleOutput(turn: TurnState | undefined) {
  return Object.values(turn?.responses ?? {}).some((response) => (
    Object.values(response.items).some((item) => {
      if (!isMessageItem(item)) return false;
      return item.content.some((part) => isOutputTextPart(part) && Boolean(part.text.trim()));
    })
  ));
}
