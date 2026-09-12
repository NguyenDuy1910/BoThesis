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

/** A Collection explicitly attached to one user turn as retrieval context. */
export interface ConversationCollection {
  id: string;
  title: string;
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
  /** The compact reference retrieval issued and the model was allowed to cite. */
  reference?: string;
  /** The reader-facing number, assigned by first use within the answer. */
  number?: number;
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

/** The Enterprise Agent citation annotation type; the specification only defines url_citation. */
export const DOCUMENT_CITATION_TYPE = "bothesis:document_citation";

/**
 * The Enterprise Agent artifact annotation type: a file the turn produced, attached to
 * the answer that presents it. Zero-width at the end of the text, and the
 * replacement for the provider's own `container_file_citation`, which the
 * backend consumes so no container or provider file id reaches a client.
 */
export const ARTIFACT_ANNOTATION_TYPE = "bothesis:artifact";

/** The description of one produced file revision; never its content. */
export interface ArtifactReference {
  id: string;
  title: string;
  file_name: string;
  mime_type: string;
  revision: number;
  size_bytes: number;
  updated_at: string;
}

/**
 * An opaque protocol annotation. Document citations carry `citation`;
 * artifacts carry `artifact`.
 */
export interface OutputTextAnnotation {
  type: string;
  start_index?: number;
  end_index?: number;
  citation?: CitationReference;
  artifact?: ArtifactReference;
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

/** A command dispatched and executed by the provider's hosted environment. */
export interface HostedExecutionCallItem extends OutputItemBase {
  type: "hosted_execution_call";
  call_id: string;
  commands: string[];
  timeout_ms?: number;
  max_output_characters?: number;
}

export interface HostedExecutionOutput {
  stdout: string;
  stderr: string;
  exit_code?: number | null;
  timed_out: boolean;
}

/** The provider's finished hosted-shell observation used by the chat renderer. */
export interface HostedExecutionResultItem extends OutputItemBase {
  type: "hosted_execution_result";
  call_id: string;
  commands: string[];
  output: HostedExecutionOutput[];
  /** Safe file names reported by the workspace; never provider file IDs. */
  workspace_files?: string[];
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
  | HostedExecutionCallItem
  | HostedExecutionResultItem
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
  /** Live-only state. It is intentionally omitted from saved conversations. */
  modelPending?: boolean;
  /** Runtime facts, never model output. They only exist during this stream. */
  runtimeActivities?: RuntimeActivity[];
}

export interface RuntimeActivity {
  callId: string;
  toolName: string;
  state: "active" | "completed" | "failed" | "timeout" | "skipped";
  startedAt: number;
  resultCount?: number;
  progress?: Record<string, unknown>;
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
      type: "tool_started";
      call_id: string;
      tool_name: string;
    })
  | (StreamEventBase & {
      type: "tool_progress";
      call_id: string;
      tool_name: string;
      data: Record<string, unknown>;
    })
  | (StreamEventBase & {
      type: "tool_completed";
      call_id: string;
      tool_name: string;
      status: "completed" | "failed" | "timeout" | "skipped";
      result_count?: number | null;
      duration_ms: number;
    })
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
  | { type: "data-document"; id?: string; data: ConversationDocument }
  | { type: "data-collection"; id?: string; data: ConversationCollection };

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
