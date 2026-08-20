export interface ChatConversation {
  id: string;
  sessionId: string;
  title: string;
  titleSource?: "generated" | "custom";
  createdAt: number;
  updatedAt: number;
  deletedAt?: number;
}

export interface CachedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  parts: ChatMessagePart[];
  createdAt: number;
}

export interface ConversationDocument {
  id: string;
  fileName: string;
  contentType: string;
  sizeBytes: number;
  mode: "direct" | "indexed";
  status: "available" | "failed";
}

export type ChatDataParts = {
  run: {
    status: "running" | "completed" | "failed" | "cancelled";
    startedAt: number;
    requestId?: string;
    conversationId?: string;
    durationMs?: number;
    modelDurationMs?: number;
    toolDurationMs?: number;
    toolCallCount?: number;
  };
  status: {
    phase: "run" | "preparing" | "document" | "model" | "tool" | "retrieval" | "done" | "cancelled" | "error";
    state: "active" | "completed" | "error" | "skipped";
    label: string;
    detail?: string;
    toolName?: string;
    toolCallId?: string;
    durationMs?: number;
    resultCount?: number;
    activityType?: "document_preparation" | "tool_execution" | "knowledge_retrieval" | "final_response_generation";
    stepId?: string;
    turn?: number;
    selectedTools?: string[];
  };
  source: {
    id: string;
    title: string;
    url?: string;
    domain?: string;
    description?: string;
    page?: string;
    section?: string;
    snippet?: string;
    mimeType?: string;
    source?: string;
    relevanceScore?: number;
    status?: "Used" | "Found" | "Reviewed" | "Restricted";
    restricted?: boolean;
  };
  "stream-error": { message: string; retryable?: boolean };
};

export type ChatMessagePart =
  | {
      type: "text";
      id?: string;
      text: string;
      state: "streaming" | "done";
      /** Assistant commentary is conversational text, but not the final answer. */
      phase?: "commentary" | "final_answer";
    }
  | { type: "data-document"; id?: string; data: ConversationDocument }
  | { type: "data-run"; id?: string; data: ChatDataParts["run"] }
  | { type: "data-status"; id?: string; data: ChatDataParts["status"] }
  | { type: "data-source"; id?: string; data: ChatDataParts["source"] }
  | { type: "data-stream-error"; id?: string; data: ChatDataParts["stream-error"] };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatMessagePart[];
  runtime?: AgentItemStore;
}

export interface AgentEvidence {
  id: string;
  document_id?: string;
  title: string;
  page?: string | null;
  section?: string | null;
  uri?: string | null;
  source?: string | null;
  snippet?: string | null;
  relevance_score?: number | null;
}

export interface AgentHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

type StreamEventMetadata = { sequence?: number; event_id?: string };

export type AgentItem =
  | {
      type: "message";
      id?: string;
      role: "assistant" | "user" | "system" | "developer";
      phase?: "commentary" | "final_answer";
      status?: "in_progress" | "completed" | "incomplete" | "failed" | "skipped";
      content: Array<{ type: "output_text" | "input_text"; text: string }>;
    }
  | {
      type: "tool_call";
      id?: string;
      call_id: string;
      name: string;
      label?: string;
      category: "retrieval" | "tool";
      status: "in_progress" | "completed" | "incomplete" | "failed" | "skipped";
    }
  | {
      type: "tool_result";
      id?: string;
      call_id: string;
      name: string;
      status: "in_progress" | "completed" | "failed" | "timeout" | "skipped";
      error?: string | null;
      duration_ms?: number | null;
      result_count?: number | null;
    }
  | ({ type: "evidence"; id?: string; status: "found" | "used" } & AgentEvidence)
  | { type: "reasoning"; id?: string; status?: string; summary?: Array<{ text: string }> };

export interface AgentItemStore {
  items: Record<string, AgentItem>;
  historyItemIds: string[];
  activeItemIds: string[];
  turnStatus: "idle" | "in_progress" | "completed" | "failed" | "cancelled";
}

export type AgentStreamEvent = StreamEventMetadata & (
  | { type: "turn.started" }
  | { type: "item.started"; item: AgentItem }
  | { type: "item.delta"; item_id: string; delta: string }
  | { type: "item.completed"; item: AgentItem }
  | {
      type: "turn.completed";
      duration_ms?: number | null;
      model_duration_ms?: number | null;
      tool_duration_ms?: number | null;
      tool_call_count?: number | null;
    }
  | { type: "error"; message: string }
);
