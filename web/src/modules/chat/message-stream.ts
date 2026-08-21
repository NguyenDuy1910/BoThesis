import type {
  ChatMessage,
  ContentPart,
  FunctionCallItem,
  MessageItem,
  OutputItem,
  OutputTextAnnotation,
  OutputTextPart,
  ResponseEnvelope,
  ResponseState,
  ResponseStreamEvent,
  TurnState,
} from "./types";

export interface OrderedOutputItem {
  id: string;
  item: OutputItem;
  outputIndex: number;
  responseId: string;
  responseIndex: number;
}

export function emptyTurnState(id: string): TurnState {
  return { id, status: "streaming", responses: {}, responseOrder: [] };
}

/**
 * The sole stream reducer. It converts protocol mutations into a materialized
 * Turn / Response / OutputItem tree; no raw event is retained for rendering.
 */
export function reduceResponseStreamEvent(
  current: TurnState,
  event: ResponseStreamEvent,
): TurnState {
  switch (event.type) {
    case "response.created":
      return reconcileResponse(
        { ...current, status: "streaming", error: undefined },
        event.response_id,
        event.response,
      );
    case "response.output_item.added":
      return upsertItem(current, event.response_id, event.output_index, event.item, false);
    case "response.output_item.done":
      return upsertItem(current, event.response_id, event.output_index, event.item, true);
    case "response.content_part.added":
    case "response.content_part.done":
      return updateMessageContent(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        event.content_index,
        () => cloneContentPart(event.part),
      );
    case "response.output_text.delta":
      return updateMessageContent(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        event.content_index,
        (part) => ({ ...part, text: part.text + event.delta }),
      );
    case "response.output_text.done":
      return updateMessageContent(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        event.content_index,
        (part) => ({ ...part, text: event.text }),
      );
    case "response.output_text.annotation.added":
      return updateMessageContent(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        event.content_index,
        (part) => ({ ...part, annotations: mergeAnnotations(part.annotations, [event.annotation]) }),
      );
    case "response.function_call_arguments.delta":
      return updateFunctionCall(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        (item) => ({ ...item, arguments: item.arguments + event.delta }),
      );
    case "response.function_call_arguments.done":
      return updateFunctionCall(
        current,
        event.response_id,
        event.item_id,
        event.output_index,
        (item) => ({ ...item, arguments: event.arguments }),
      );
    case "response.completed": {
      const next = reconcileResponse(current, event.response.id, event.response);
      const response = next.responses[event.response.id];
      return {
        ...next,
        // A function call leaves the enclosing Turn active while the agent
        // executes it and starts a later response. This never leaks sampling
        // terminology into the UI.
        status: response && hasFunctionCalls(response) ? "streaming" : "completed",
        error: undefined,
      };
    }
    case "response.incomplete":
    case "response.failed": {
      const next = reconcileResponse(current, event.response.id, event.response);
      return {
        ...next,
        status: "failed",
        error: responseFailureMessage(event.response),
      };
    }
  }
}

export function applyResponseStreamEvent(
  messages: ChatMessage[],
  assistantId: string,
  event: ResponseStreamEvent,
): ChatMessage[] {
  return messages.map((message) => {
    if (message.id !== assistantId) return message;
    return {
      ...message,
      turn: reduceResponseStreamEvent(message.turn ?? emptyTurnState(message.id), event),
    };
  });
}

/** Mark a locally interrupted request as failed without inventing a stream event. */
export function failTurn(turn: TurnState, message: string): TurnState {
  return { ...turn, status: "failed", error: message };
}

/** Flatten semantic response ordering for the item renderer. */
export function orderedTurnItems(turn: TurnState | undefined): OrderedOutputItem[] {
  if (!turn) return [];
  return turn.responseOrder.flatMap((responseId, responseIndex) => {
    const response = turn.responses[responseId];
    if (!response) return [];
    return response.itemOrder.flatMap((id, outputIndex) => {
      const item = response.items[id];
      return item ? [{ id, item, outputIndex, responseId, responseIndex }] : [];
    });
  });
}

/** The final response is what should be copied into the next chat request. */
export function finalTurnText(turn: TurnState | undefined): string {
  if (!turn) return "";
  const finalResponseId = turn.responseOrder.at(-1);
  const response = finalResponseId ? turn.responses[finalResponseId] : undefined;
  if (!response) return "";
  return response.itemOrder
    .map((id) => response.items[id])
    .filter(isMessageItem)
    .filter((item) => item.role === "assistant")
    .flatMap((item) => item.content)
    .filter(isOutputTextPart)
    .map((part) => part.text)
    .join("");
}

export function isMessageItem(item: OutputItem | undefined): item is MessageItem {
  return item?.type === "message" && Array.isArray((item as Partial<MessageItem>).content);
}

export function isFunctionCallItem(item: OutputItem | undefined): item is FunctionCallItem {
  return item?.type === "function_call"
    && typeof (item as Partial<FunctionCallItem>).call_id === "string"
    && typeof (item as Partial<FunctionCallItem>).name === "string";
}

export function isOutputTextPart(part: ContentPart): part is OutputTextPart {
  return part.type === "output_text"
    && typeof (part as Partial<OutputTextPart>).text === "string";
}

function reconcileResponse(
  current: TurnState,
  responseId: string,
  response: ResponseEnvelope,
): TurnState {
  const existing = current.responses[responseId] ?? emptyResponseState(responseId, response.status);
  let nextResponse: ResponseState = { ...existing, status: response.status };
  for (const [index, item] of response.output.entries()) {
    nextResponse = upsertResponseItem(nextResponse, responseId, index, item, true);
  }
  return withResponse(current, nextResponse);
}

function upsertItem(
  current: TurnState,
  responseId: string,
  outputIndex: number,
  item: OutputItem,
  done: boolean,
): TurnState {
  const response = current.responses[responseId]
    ?? emptyResponseState(responseId, "in_progress");
  return withResponse(
    current,
    upsertResponseItem(response, responseId, outputIndex, item, done),
  );
}

function updateMessageContent(
  current: TurnState,
  responseId: string,
  itemId: string,
  outputIndex: number,
  contentIndex: number,
  update: (part: OutputTextPart) => ContentPart,
): TurnState {
  const response = current.responses[responseId]
    ?? emptyResponseState(responseId, "in_progress");
  const key = itemKey(response, itemId, outputIndex, responseId);
  const existing = response.items[key];
  const message = isMessageItem(existing) ? existing : syntheticMessage(itemId);
  const content = [...message.content];
  const previous = content[contentIndex];
  const textPart = previous && isOutputTextPart(previous)
    ? previous
    : { type: "output_text" as const, text: "", annotations: [] };
  content[contentIndex] = update(textPart);
  const nextItem: MessageItem = { ...message, id: itemId, content };
  return withResponse(current, replaceResponseItem(response, key, nextItem, outputIndex));
}

function updateFunctionCall(
  current: TurnState,
  responseId: string,
  itemId: string,
  outputIndex: number,
  update: (item: FunctionCallItem) => FunctionCallItem,
): TurnState {
  const response = current.responses[responseId]
    ?? emptyResponseState(responseId, "in_progress");
  const key = itemKey(response, itemId, outputIndex, responseId);
  const existing = response.items[key];
  const item = isFunctionCallItem(existing)
    ? existing
    : {
        type: "function_call" as const,
        id: itemId,
        call_id: itemId,
        name: "tool",
        arguments: "",
        status: "in_progress" as const,
      };
  return withResponse(current, replaceResponseItem(response, key, update(item), outputIndex));
}

function withResponse(current: TurnState, response: ResponseState): TurnState {
  return {
    ...current,
    responses: { ...current.responses, [response.id]: response },
    responseOrder: current.responseOrder.includes(response.id)
      ? current.responseOrder
      : [...current.responseOrder, response.id],
  };
}

function emptyResponseState(id: string, status: ResponseState["status"]): ResponseState {
  return { id, status, items: {}, itemOrder: [] };
}

function upsertResponseItem(
  response: ResponseState,
  responseId: string,
  outputIndex: number,
  incoming: OutputItem,
  done: boolean,
): ResponseState {
  const key = itemKey(response, incoming.id, outputIndex, responseId);
  const previous = response.items[key];
  const item = mergeOutputItem(previous, incoming, key, done);
  return replaceResponseItem(response, key, item, outputIndex);
}

function replaceResponseItem(
  response: ResponseState,
  key: string,
  item: OutputItem,
  outputIndex: number,
): ResponseState {
  const itemOrder = [...response.itemOrder];
  const currentIndex = itemOrder.indexOf(key);
  if (currentIndex === -1) itemOrder.splice(Math.min(outputIndex, itemOrder.length), 0, key);
  else if (currentIndex !== outputIndex && outputIndex < itemOrder.length) {
    itemOrder.splice(currentIndex, 1);
    itemOrder.splice(outputIndex, 0, key);
  }
  return { ...response, items: { ...response.items, [key]: item }, itemOrder };
}

function itemKey(
  response: ResponseState,
  itemId: string | undefined,
  outputIndex: number,
  responseId: string,
): string {
  if (itemId && response.items[itemId]) return itemId;
  if (itemId) return itemId;
  return response.itemOrder[outputIndex] ?? `${responseId}:output:${outputIndex}`;
}

function mergeOutputItem(
  previous: OutputItem | undefined,
  incoming: OutputItem,
  id: string,
  done: boolean,
): OutputItem {
  const normalized = cloneOutputItem({
    ...incoming,
    id: incoming.id ?? id,
    status: incoming.status ?? (done ? "completed" : "in_progress"),
  });
  if (!isMessageItem(previous) || !isMessageItem(normalized)) return normalized;
  return {
    ...previous,
    ...normalized,
    content: normalized.content.map((part, index) => {
      const current = previous.content[index];
      if (!isOutputTextPart(part) || !current || !isOutputTextPart(current)) return part;
      return {
        ...part,
        // The final item is allowed to omit text because it was already sent
        // through delta events. Keep the same materialized message instance.
        text: part.text || current.text,
        annotations: mergeAnnotations(current.annotations, part.annotations),
      };
    }),
  };
}

function cloneOutputItem(item: OutputItem): OutputItem {
  if (!isMessageItem(item)) return { ...item };
  return { ...item, content: item.content.map(cloneContentPart) };
}

function cloneContentPart(part: ContentPart): ContentPart {
  if (!isOutputTextPart(part)) return { ...part };
  return { ...part, annotations: [...(part.annotations ?? [])] };
}

function mergeAnnotations(
  current: OutputTextAnnotation[],
  next: OutputTextAnnotation[],
): OutputTextAnnotation[] {
  const annotations = [...current];
  const fingerprints = new Set(current.map(annotationFingerprint));
  for (const annotation of next) {
    const fingerprint = annotationFingerprint(annotation);
    if (fingerprints.has(fingerprint)) continue;
    fingerprints.add(fingerprint);
    annotations.push(annotation);
  }
  return annotations;
}

function annotationFingerprint(annotation: OutputTextAnnotation) {
  return JSON.stringify(annotation);
}

function syntheticMessage(id: string): MessageItem {
  return {
    type: "message",
    id,
    role: "assistant",
    status: "in_progress",
    content: [],
  };
}

function hasFunctionCalls(response: ResponseState): boolean {
  return response.itemOrder.some((id) => isFunctionCallItem(response.items[id]));
}

function responseFailureMessage(response: ResponseEnvelope): string {
  return response.error?.message
    ?? response.incomplete_details?.reason
    ?? "The response could not be completed.";
}
