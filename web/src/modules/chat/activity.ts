export type AgentRunStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

export type ActivityStepType = "planning" | "tool" | "retrieval" | "generation" | "completion";

export type ActivityStepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type SourceType =
  | "jira"
  | "confluence"
  | "notion"
  | "google-docs"
  | "google-sheets"
  | "google-slides"
  | "excel"
  | "csv"
  | "document"
  | "pdf"
  | "word"
  | "presentation"
  | "text"
  | "image"
  | "web"
  | "database"
  | "unknown";

export type SourceStatus = "Used" | "Found" | "Reviewed" | "Restricted";

export interface ActivityEntry {
  id: string;
  type: ActivityStepType;
  label: string;
  status: ActivityStepStatus;
  durationMs?: number;
  description?: string;
  toolName?: string;
  query?: string;
  resultCount?: number;
  sourceIds: string[];
}

export interface SourceResult {
  id: string;
  title: string;
  domain: string;
  url?: string;
  description?: string;
  type: SourceType;
  provider?: string;
  fileType?: string;
  relevanceScore?: number;
  status: SourceStatus;
}

export interface AgentRunView {
  status: AgentRunStatus;
  startedAt?: number;
  durationMs?: number;
  modelDurationMs?: number;
  toolDurationMs?: number;
  toolCallCount?: number;
  steps: ActivityEntry[];
  sources: SourceResult[];
  sourceCount: number;
  usedSourceCount: number;
  hasActivity: boolean;
}
