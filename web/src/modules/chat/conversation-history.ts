import type {
  AgentHistoryMessage,
  ChatMessage,
  ChatMessagePart,
  ConversationDocument,
} from "./types";
import { getMessageText } from "./conversations.ts";

export const MAX_HISTORY_MESSAGES = 24;
export const MAX_HISTORY_CHARACTERS = 24_000;
export const MAX_HISTORY_MESSAGE_CHARACTERS = 8_000;
const CLIP_MARKER = "\n…\n";

export function conversationMessageText(message: ChatMessage) {
  return getMessageText(message).trim();
}

export function historyFromMessages(messages: ChatMessage[]): AgentHistoryMessage[] {
  let remainingCharacters = MAX_HISTORY_CHARACTERS;
  const selected: AgentHistoryMessage[] = [];

  for (const message of [...messages].reverse()) {
    const content = clipHistoryMessage(conversationMessageText(message));
    if (!content) continue;
    if (selected.length === MAX_HISTORY_MESSAGES || content.length > remainingCharacters) {
      break;
    }
    selected.push({ role: message.role, content });
    remainingCharacters -= content.length;
  }

  selected.reverse();
  // Never send an assistant answer after dropping the user request that
  // introduced it at a history budget boundary.
  while (selected[0]?.role === "assistant") selected.shift();
  return selected;
}

function clipHistoryMessage(content: string) {
  if (content.length <= MAX_HISTORY_MESSAGE_CHARACTERS) return content;
  const available = MAX_HISTORY_MESSAGE_CHARACTERS - CLIP_MARKER.length;
  const leadingCharacters = Math.ceil(available * 0.6);
  const trailingCharacters = available - leadingCharacters;
  return `${content.slice(0, leadingCharacters)}${CLIP_MARKER}${content.slice(-trailingCharacters)}`;
}

export function regenerationContext(
  messages: ChatMessage[],
  targetId?: string,
): {
  userText: string;
  historyMessages: ChatMessage[];
  displayMessages: ChatMessage[];
  documents: ConversationDocument[];
} | null {
  const targetIndex = targetId
    ? messages.findIndex((message) => message.id === targetId)
    : messages.length;
  const user = messages
    .slice(0, targetIndex < 0 ? messages.length : targetIndex)
    .reverse()
    .find((message) => message.role === "user");
  if (!user) return null;
  const userIndex = messages.indexOf(user);
  const userText = conversationMessageText(user);
  if (!userText) return null;
  return {
    userText,
    historyMessages: messages.slice(0, userIndex),
    displayMessages: messages.slice(0, userIndex + 1),
    documents: user.parts
      .filter((part): part is Extract<ChatMessagePart, { type: "data-document" }> => (
        part.type === "data-document"
      ))
      .map((part) => part.data),
  };
}
