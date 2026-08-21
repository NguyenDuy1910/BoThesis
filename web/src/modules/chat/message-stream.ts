import type {
  ChatMessage,
  ContentPart,
  FunctionCallItem,
  MessageItem,
  OutputItem,
  OutputTextAnnotation,
  OutputTextPart,
  ReasoningItem,
  ResponseEnvelope,
  ResponseState,
  ResponseStreamEvent,
  SummaryTextPart,
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
 * The sole stream reducer. It folds OpenResponses events into a materialized
 * Turn / Response / OutputItem tree; no raw event is retained for rendering.
 *
 * Item-level events carry no response id, exactly as the specification defines
 * them: the response being mutated is the one opened by the most recent
 * `response.created`, tracked here as `currentResponseId`.
 */
export function reduceResponseStreamEvent(
  current: TurnState,
  event: ResponseStreamEvent,
): TurnState {
  switch (event.type) {
    case "response.created":
    case "response.queued":
    case "response.in_progress":
      return {
        ...reconcileResponse(current, event.response),
        currentResponseId: event.response.id,
        status: "streaming",
        error: undefined,
      };
    case "response.output_item.added":
      return upsertItem(current, event.output_index, event.item, false);
    case "response.output_item.done":
      return upsertItem(current, event.output_index, event.item, true);
    case "response.content_part.added":
    case "response.content_part.done":
      return updateContent(current, event, () => cloneContentPart(event.part));
    case "response.output_text.delta":
      return updateContent(current, event, (part) => ({
        ...part,
        text: part.text + event.delta,
      }));
    case "response.output_text.done":
      return updateContent(current, event, (part) => ({ ...part, text: event.text }));
    case "response.refusal.delta":
      return updateContent(current, event, () => ({
        type: "refusal",
        refusal: event.delta,
      }));
    case "response.refusal.done":
      return updateContent(current, event, () => ({
        type: "refusal",
        refusal: event.refusal,
      }));
    case "response.output_text.annotation.added":
      return updateContent(current, event, (part) => ({
        ...part,
        annotations: insertAnnotation(
          part.annotations,
          event.annotation_index,
          event.annotation,
        ),
      }));
    case "response.reasoning.delta":
      return updateReasoning(current, event, "content", event.content_index, (text) =>
        text + event.delta);
    case "response.reasoning.done":
      return updateReasoning(
        current,
        event,
        "content",
        event.content_index,
        () => event.text,
      );
    case "response.reasoning_summary_part.added":
    case "response.reasoning_summary_part.done":
      return updateReasoning(current, event, "summary", event.summary_index, () =>
        partText(event.part));
    case "response.reasoning_summary_text.delta":
      return updateReasoning(current, event, "summary", event.summary_index, (text) =>
        text + event.delta);
    case "response.reasoning_summary_text.done":
      return updateReasoning(
        current,
        event,
        "summary",
        event.summary_index,
        () => event.text,
      );
    case "response.function_call_arguments.delta":
      return updateFunctionCall(current, event.item_id, event.output_index, (item) => ({
        ...item,
        arguments: item.arguments + event.delta,
      }));
    case "response.function_call_arguments.done":
      return updateFunctionCall(current, event.item_id, event.output_index, (item) => ({
        ...item,
        arguments: event.arguments,
      }));
    case "response.completed": {
      const next = reconcileResponse(current, event.response);
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
      const next = reconcileResponse(current, event.response);
      return {
        ...next,
        status: "failed",
        error: responseFailureMessage(event.response),
      };
    }
    case "error":
      return { ...current, status: "failed", error: event.error.message };
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

/**
 * The text to carry into the next request. The final response's `final_answer`
 * messages are the answer; a provider that omits `phase` yields every
 * assistant message instead.
 */
export function finalTurnText(turn: TurnState | undefined): string {
  if (!turn) return "";
  const finalResponseId = turn.responseOrder.at(-1);
  const response = finalResponseId ? turn.responses[finalResponseId] : undefined;
  if (!response) return "";
  const messages = response.itemOrder
    .map((id) => response.items[id])
    .filter(isMessageItem)
    .filter((item) => item.role === "assistant");
  const answers = messages.filter((item) => item.phase === "final_answer");
  const selected = answers.length > 0
    ? answers
    : messages.filter((item) => item.phase !== "commentary");
  return selected
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

export function isReasoningItem(item: OutputItem | undefined): item is ReasoningItem {
  return item?.type === "reasoning";
}

export function isOutputTextPart(part: ContentPart): part is OutputTextPart {
  return part.type === "output_text"
    && typeof (part as Partial<OutputTextPart>).text === "string";
}

interface ContentAddress {
  item_id: string;
  output_index: number;
  content_index: number;
}

interface SummaryAddress {
  item_id: string;
  output_index: number;
}

function reconcileResponse(current: TurnState, response: ResponseEnvelope): TurnState {
  const existing = current.responses[response.id]
    ?? emptyResponseState(response.id, response.status);
  let next: ResponseState = {
    ...existing,
    status: response.status,
    previousResponseId: response.previous_response_id ?? existing.previousResponseId,
  };
  for (const [index, item] of response.output.entries()) {
    next = upsertResponseItem(next, index, item, true);
  }
  return withResponse(current, next);
}

function upsertItem(
  current: TurnState,
  outputIndex: number,
  item: OutputItem,
  done: boolean,
): TurnState {
  const response = activeResponse(current);
  return withResponse(current, upsertResponseItem(response, outputIndex, item, done));
}

function updateContent(
  current: TurnState,
  address: ContentAddress,
  update: (part: OutputTextPart) => ContentPart,
): TurnState {
  const response = activeResponse(current);
  const key = itemKey(response, address.item_id, address.output_index);
  const existing = response.items[key];
  const message = isMessageItem(existing) ? existing : syntheticMessage(address.item_id);
  const content = [...message.content];
  const previous = content[address.content_index];
  const textPart = previous && isOutputTextPart(previous)
    ? previous
    : { type: "output_text" as const, text: "", annotations: [] };
  content[address.content_index] = update(textPart);
  const nextItem: MessageItem = { ...message, id: address.item_id, content };
  return withResponse(
    current,
    replaceResponseItem(response, key, nextItem, address.output_index),
  );
}

function updateReasoning(
  current: TurnState,
  address: SummaryAddress,
  field: "content" | "summary",
  index: number,
  update: (text: string) => string,
): TurnState {
  const response = activeResponse(current);
  const key = itemKey(response, address.item_id, address.output_index);
  const existing = response.items[key];
  const item: ReasoningItem = isReasoningItem(existing)
    ? existing
    : { type: "reasoning", id: address.item_id, status: "in_progress", summary: [] };
  const parts = [...(item[field] ?? [])];
  const previous = parts[index];
  parts[index] = {
    type: field === "summary" ? "summary_text" : "reasoning_text",
    text: update(previous ? partText(previous) : ""),
  } as SummaryTextPart;
  return withResponse(
    current,
    replaceResponseItem(
      response,
      key,
      { ...item, id: address.item_id, [field]: parts },
      address.output_index,
    ),
  );
}

function updateFunctionCall(
  current: TurnState,
  itemId: string,
  outputIndex: number,
  update: (item: FunctionCallItem) => FunctionCallItem,
): TurnState {
  const response = activeResponse(current);
  const key = itemKey(response, itemId, outputIndex);
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
  return withResponse(
    current,
    replaceResponseItem(response, key, update(item), outputIndex),
  );
}

/**
 * The response currently being mutated. A stream always opens one with
 * `response.created`; a placeholder only guards against a truncated stream.
 */
function activeResponse(current: TurnState): ResponseState {
  const id = current.currentResponseId ?? current.responseOrder.at(-1);
  if (id && current.responses[id]) return current.responses[id];
  return emptyResponseState(id ?? "response", "in_progress");
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
  outputIndex: number,
  incoming: OutputItem,
  done: boolean,
): ResponseState {
  const key = itemKey(response, incoming.id, outputIndex);
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
): string {
  if (itemId) return itemId;
  return response.itemOrder[outputIndex] ?? `${response.id}:output:${outputIndex}`;
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
  if (isReasoningItem(previous) && isReasoningItem(normalized)) {
    return {
      ...previous,
      ...normalized,
      // The final item may repeat only the shell; keep what was streamed.
      content: normalized.content?.length ? normalized.content : previous.content,
      summary: normalized.summary?.length ? normalized.summary : previous.summary,
    };
  }
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

function partText(part: ContentPart): string {
  return typeof (part as { text?: unknown }).text === "string"
    ? (part as { text: string }).text
    : "";
}

function insertAnnotation(
  current: OutputTextAnnotation[],
  index: number,
  annotation: OutputTextAnnotation,
): OutputTextAnnotation[] {
  const annotations = [...current];
  annotations.splice(Math.min(index, annotations.length), 0, annotation);
  return annotations;
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
