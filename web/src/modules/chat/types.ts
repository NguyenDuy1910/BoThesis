export interface ChatConversation {
  id: string;
  sessionId: string;
  title: string;
  titleSource?: "generated" | "custom";
  createdAt: number;
  updatedAt: number;
  deletedAt?: number;
}

export interface ConversationDocument {
  id: string;
  fileName: string;
  contentType: string;
  sizeBytes: number;
  mode: "direct" | "indexed";
  status: "available" | "failed";
}

export type OutputItemStatus =
  | "in_progress"
  | "completed"
  | "incomplete"
  | "failed"
  | "skipped";

export type ResponseStatus =
  | "queued"
  | "in_progress"
  | "completed"
  | "incomplete"
  | "failed"
  | "cancelled";

export interface CitationReference {
  id?: string;
  document_id?: string;
  title?: string;
  page?: string | number | null;
  section?: string | null;
  uri?: string | null;
  source?: string | null;
  restricted?: boolean;
}

/** An opaque protocol annotation. Citation annotations carry ``citation``. */
export interface OutputTextAnnotation {
  type: string;
  start_index?: number;
  end_index?: number;
  citation?: CitationReference;
  [key: string]: unknown;
}

export interface OutputTextPart {
  type: "output_text";
  text: string;
  annotations: OutputTextAnnotation[];
}

export interface InputTextPart {
  type: "input_text";
  text: string;
}

export interface RefusalPart {
  type: "refusal";
  refusal: string;
}

/** Keep provider-specific parts intact even when the UI does not render them. */
export interface ExtensionContentPart {
  type: string;
  [key: string]: unknown;
}

export type ContentPart =
  | OutputTextPart
  | InputTextPart
  | RefusalPart
  | ExtensionContentPart;

interface OutputItemBase {
  id?: string;
  type: string;
  status?: OutputItemStatus;
}

export interface MessageItem extends OutputItemBase {
  type: "message";
  role: "assistant" | "user" | "system" | "developer";
  content: ContentPart[];
}

export interface FunctionCallItem extends OutputItemBase {
  type: "function_call";
  call_id: string;
  name: string;
  arguments: string;
}

export interface FunctionCallOutputItem extends OutputItemBase {
  type: "function_call_output";
  call_id: string;
  output: string;
}

export interface ReasoningItem extends OutputItemBase {
  type: "reasoning";
  summary: Array<{ type: "summary_text"; text: string }>;
  encrypted_content?: string | null;
}

/** A provider extension is retained for replay and future renderers. */
export interface ExtensionOutputItem extends OutputItemBase {
  [key: string]: unknown;
}

export type OutputItem =
  | MessageItem
  | FunctionCallItem
  | FunctionCallOutputItem
  | ReasoningItem
  | ExtensionOutputItem;

export interface ResponseEnvelope {
  id: string;
  status: ResponseStatus;
  output: OutputItem[];
  error?: { code?: string; message?: string } | null;
  incomplete_details?: { reason?: string } | null;
}

/** One materialized provider response inside a user-visible turn. */
export interface ResponseState {
  id: string;
  status: ResponseStatus;
  items: Record<string, OutputItem>;
  itemOrder: string[];
}

/**
 * Client state is semantic, not an event log. Responses remain separate so a
 * completed sampling response can be followed by another response in the
 * same Turn after function execution.
 */
export interface TurnState {
  id: string;
  status: "streaming" | "completed" | "failed";
  responses: Record<string, ResponseState>;
  responseOrder: string[];
  error?: string;
}

export type ResponseStreamEvent = { sequence_number?: number } & (
  | { type: "response.created"; response_id: string; response: ResponseEnvelope }
  | {
      type: "response.output_item.added";
      response_id: string;
      output_index: number;
      item: OutputItem;
    }
  | {
      type: "response.content_part.added";
      response_id: string;
      item_id: string;
      output_index: number;
      content_index: number;
      part: ContentPart;
    }
  | {
      type: "response.content_part.done";
      response_id: string;
      item_id: string;
      output_index: number;
      content_index: number;
      part: ContentPart;
    }
  | {
      type: "response.output_text.delta";
      response_id: string;
      item_id: string;
      output_index: number;
      content_index: number;
      delta: string;
    }
  | {
      type: "response.output_text.done";
      response_id: string;
      item_id: string;
      output_index: number;
      content_index: number;
      text: string;
    }
  | {
      type: "response.output_text.annotation.added";
      response_id: string;
      item_id: string;
      output_index: number;
      content_index: number;
      annotation: OutputTextAnnotation;
    }
  | {
      type: "response.function_call_arguments.delta";
      response_id: string;
      item_id: string;
      output_index: number;
      delta: string;
    }
  | {
      type: "response.function_call_arguments.done";
      response_id: string;
      item_id: string;
      output_index: number;
      arguments: string;
    }
  | {
      type: "response.output_item.done";
      response_id: string;
      output_index: number;
      item: OutputItem;
    }
  | { type: "response.completed"; response: ResponseEnvelope }
  | { type: "response.incomplete"; response: ResponseEnvelope }
  | { type: "response.failed"; response: ResponseEnvelope }
);

export type ChatMessagePart =
  | {
      type: "text";
      id?: string;
      text: string;
      state: "streaming" | "done";
      annotations?: OutputTextAnnotation[];
    }
  | { type: "data-document"; id?: string; data: ConversationDocument };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatMessagePart[];
  turn?: TurnState;
}

export interface CachedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  parts: ChatMessagePart[];
  /** Retain semantic item ordering when a conversation is restored. */
  turn?: TurnState;
  createdAt: number;
}

export interface AgentHistoryMessage {
  role: "user" | "assistant";
  content: string;
}
