import type { ChatMessagePart } from "./types";

type StatusPart = Extract<ChatMessagePart, { type: "data-status" }>;

export function upsertStatusPart(
  parts: ChatMessagePart[],
  nextStatus: StatusPart,
): ChatMessagePart[] {
  const stepId = nextStatus.data.stepId ?? nextStatus.id;
  const index = parts.findIndex((part) => (
    part.type === "data-status" && (part.data.stepId ?? part.id) === stepId
  ));
  if (index === -1) return [...parts, nextStatus];
  const current = parts[index] as StatusPart;
  return [
    ...parts.slice(0, index),
    {
      ...current,
      ...nextStatus,
      data: { ...current.data, ...nextStatus.data },
    },
    ...parts.slice(index + 1),
  ];
}
