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

/** The OpenResponses item state machine. */
export type OutputItemStatus = "in_progress" | "completed" | "incomplete";

/** Whether an assistant message is intermediate commentary or the answer. */
export type MessagePhase = "commentary" | "final_answer";

export type ResponseStatus =
  | "queued"
  | "in_progress"
  | "completed"
  | "incomplete"
  | "failed"
  | "cancelled";

export interface CitationReference {
  id?: string;
  item_id?: string;
  chunk_id?: string;
  title?: string;
  section?: string | null;
  section_path?: string[] | null;
  anchor?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  spans?: CitationSpan[] | null;
  source?: CitationSource | null;
  internal_url?: string | null;
  original_url?: string | null;
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CitationSpan {
  page?: number | null;
  element_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  bounding_box?: BoundingBox | null;
}

export interface CitationSource {
  connector_id?: string | number;
  provider?: string;
  external_id?: string;
  url?: string | null;
}

/** The one BoThesis annotation type; the specification only defines url_citation. */
export const DOCUMENT_CITATION_TYPE = "bothesis:document_citation";

/** An opaque protocol annotation. Document citations carry `citation`. */
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

export interface ReasoningTextPart {
  type: "reasoning_text";
  text: string;
}

export interface SummaryTextPart {
  type: "summary_text";
  text: string;
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
  | ReasoningTextPart
  | SummaryTextPart
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
  /** Absent until the response settles, or when the provider omits it. */
  phase?: MessagePhase | null;
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
  /** Raw reasoning text, when the provider exposes it. */
  content?: Array<ReasoningTextPart | SummaryTextPart>;
  summary: Array<SummaryTextPart>;
  /** The opaque blob a provider needs to continue a reasoning session. */
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
  /** The response this one continues, which chains a turn's responses. */
  previous_response_id?: string | null;
  error?: { code?: string; message?: string } | null;
  incomplete_details?: { reason?: string } | null;
}

/** One materialized provider response inside a user-visible turn. */
export interface ResponseState {
  id: string;
  status: ResponseStatus;
  items: Record<string, OutputItem>;
  itemOrder: string[];
  previousResponseId?: string;
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
  /**
   * The response opened by the most recent `response.created`. Item-level
   * events carry no response id — the specification identifies the response
   * being mutated by the lifecycle events that bracket it.
   */
  currentResponseId?: string;
  error?: string;
}

interface StreamEventBase {
  sequence_number?: number;
}

/** An event addressing one content part of one output item. */
interface ContentEventBase extends StreamEventBase {
  item_id: string;
  output_index: number;
  content_index: number;
}

/** An event addressing one reasoning summary part of one output item. */
interface SummaryEventBase extends StreamEventBase {
  item_id: string;
  output_index: number;
  summary_index: number;
}

/**
 * The OpenResponses server-sent event union. No event carries a response id:
 * the response being mutated is the one opened by the most recent
 * `response.created`, and `previous_response_id` chains the several responses
 * one agent turn produces.
 */
export type ResponseStreamEvent =
  | (StreamEventBase & {
      type:
        | "response.created"
        | "response.queued"
        | "response.in_progress"
        | "response.completed"
        | "response.incomplete"
        | "response.failed";
      response: ResponseEnvelope;
    })
  | (StreamEventBase & {
      type: "response.output_item.added" | "response.output_item.done";
      output_index: number;
      item: OutputItem;
    })
  | (ContentEventBase & {
      type: "response.content_part.added" | "response.content_part.done";
      part: ContentPart;
    })
  | (ContentEventBase & { type: "response.output_text.delta"; delta: string })
  | (ContentEventBase & { type: "response.output_text.done"; text: string })
  | (ContentEventBase & {
      type: "response.output_text.annotation.added";
      annotation_index: number;
      annotation: OutputTextAnnotation;
    })
  | (ContentEventBase & { type: "response.refusal.delta"; delta: string })
  | (ContentEventBase & { type: "response.refusal.done"; refusal: string })
  | (ContentEventBase & { type: "response.reasoning.delta"; delta: string })
  | (ContentEventBase & { type: "response.reasoning.done"; text: string })
  | (SummaryEventBase & {
      type:
        | "response.reasoning_summary_part.added"
        | "response.reasoning_summary_part.done";
      part: ContentPart;
    })
  | (SummaryEventBase & {
      type: "response.reasoning_summary_text.delta";
      delta: string;
    })
  | (SummaryEventBase & {
      type: "response.reasoning_summary_text.done";
      text: string;
    })
  | (StreamEventBase & {
      type: "response.function_call_arguments.delta";
      item_id: string;
      output_index: number;
      delta: string;
    })
  | (StreamEventBase & {
      type: "response.function_call_arguments.done";
      item_id: string;
      output_index: number;
      arguments: string;
    })
  | (StreamEventBase & {
      type: "error";
      error: { type?: string; code?: string | null; message: string };
    });

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
