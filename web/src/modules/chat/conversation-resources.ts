import { turnArtifacts } from "./artifacts.ts";
import { answerSources } from "./sources.ts";
import type { ChatMessage, ChatMessagePart } from "./types";

export type ConversationResourceKind = "attachment" | "source" | "artifact";

export interface ConversationResource {
  id: string;
  title: string;
  kind: ConversationResourceKind;
  turn: number;
}

/**
 * A concise view of the resources the durable conversation makes available to
 * later turns. It mirrors existing conversation links; it does not grant or
 * cache any access itself.
 */
export function conversationResources(messages: ChatMessage[]): ConversationResource[] {
  const resources = new Map<string, ConversationResource>();
  let turn = 0;

  for (const message of messages) {
    if (message.role === "user") {
      turn += 1;
      for (const document of message.parts.filter(isDocumentPart)) {
        addResource(resources, {
          id: `attachment:${document.data.id}`,
          title: document.data.fileName,
          kind: "attachment",
          turn,
        });
      }
      continue;
    }

    for (const source of answerSources(message.turn)) {
      addResource(resources, {
        id: `source:${source.itemId}`,
        title: source.title,
        kind: "source",
        turn: Math.max(turn, 1),
      });
    }
    for (const artifact of turnArtifacts(message.turn)) {
      addResource(resources, {
        id: `artifact:${artifact.id}`,
        title: artifact.fileName,
        kind: "artifact",
        turn: Math.max(turn, 1),
      });
    }
  }
  return [...resources.values()];
}

function addResource(
  resources: Map<string, ConversationResource>,
  resource: ConversationResource,
) {
  if (!resources.has(resource.id)) resources.set(resource.id, resource);
}

function isDocumentPart(
  part: ChatMessagePart,
): part is Extract<ChatMessagePart, { type: "data-document" }> {
  return part.type === "data-document";
}
