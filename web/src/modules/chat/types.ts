import type { AgentActivityType } from "./activity";

export interface ChatConversation {
  id: string;
  sessionId: string;
  title: string;
  titleSource?: "generated" | "custom";
  createdAt: number;
  updatedAt: number;
}

export interface CachedChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  parts: ChatMessagePart[];
  createdAt: number;
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
    phase: "run" | "preparing" | "model" | "tool" | "retrieval" | "done" | "cancelled" | "error";
    state: "active" | "completed" | "error" | "skipped";
    label: string;
    detail?: string;
    toolName?: string;
    toolCallId?: string;
    durationMs?: number;
    resultCount?: number;
    activityType?: AgentActivityType;
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
  reasoning: {
    source: "model" | "provider";
    turn: number;
    text: string;
    state: "streaming" | "done";
  };
  finding: { text: string };
  "stream-error": { message: string; retryable?: boolean };
};

export type ChatMessagePart =
  | { type: "text"; text: string; state: "streaming" | "done" }
  | { type: "data-run"; id?: string; data: ChatDataParts["run"] }
  | { type: "data-status"; id?: string; data: ChatDataParts["status"] }
  | { type: "data-source"; id?: string; data: ChatDataParts["source"] }
  | { type: "data-reasoning"; id?: string; data: ChatDataParts["reasoning"] }
  | { type: "data-finding"; id?: string; data: ChatDataParts["finding"] }
  | { type: "data-stream-error"; id?: string; data: ChatDataParts["stream-error"] };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  parts: ChatMessagePart[];
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

export type AssistantPhase = "commentary" | "tool_activity" | "intermediate_finding" | "final_answer";

type StreamEventMetadata = { sequence?: number; event_id?: string };

export type AgentStreamEvent = StreamEventMetadata & (
  | { type: "run_started"; conversation_id?: string | null; request_id?: string | null }
  | { type: "turn_started"; turn: number }
  | { type: "generation_started"; turn: number }
  | {
      type: "generation_completed";
      turn: number;
      generation_kind: "next_step" | "final_response";
      finish_reason?: string | null;
      tool_call_count: number;
      selected_tools: string[];
      duration_ms: number;
    }
  | { type: "message_delta"; text: string }
  | { type: "final_answer_delta"; text: string }
  | { type: "commentary_delta"; text: string }
  | { type: "intermediate_finding_delta"; text: string }
  | { type: "public_reasoning_started"; turn: number }
  | { type: "public_reasoning_delta"; turn: number; text: string }
  | { type: "public_reasoning_completed"; turn: number }
  | { type: "provider_reasoning_summary_delta"; turn: number; text: string }
  | {
      type: "tool_started";
      activity_id?: string;
      label?: string;
      category?: "retrieval" | "tool";
      attempt?: number;
      call_id?: string;
      name?: string;
      arguments?: Record<string, unknown>;
    }
  | {
      type: "tool_completed";
      activity_id?: string;
      label?: string;
      category?: "retrieval" | "tool";
      status?: "completed" | "failed" | "timeout" | "skipped";
      attempt?: number;
      message?: string | null;
      call_id?: string;
      name?: string;
      error?: string | null;
      duration_ms?: number | null;
      result_count?: number | null;
    }
  | { type: "citation_available"; evidence: AgentEvidence }
  | { type: "citation"; evidence_id: string; title: string; page?: string | null; uri?: string | null }
  | { type: "turn_completed"; turn: number; outcome: "tool" | "final" }
  | {
      type: "run_completed";
      duration_ms?: number | null;
      model_duration_ms?: number | null;
      tool_duration_ms?: number | null;
      tool_call_count?: number | null;
    }
  | { type: "run_failed"; error: string }
);
