import type {
  ActivityEntry,
  ActivityStepStatus,
  AgentActivityType,
  AgentRunStatus,
  AgentRunView,
  SourceResult,
  SourceStatus,
  SourceType,
} from "./activity";
import type { ChatMessagePart } from "./types";

export class AgentActivityMapper {
  static fromParts(parts: ChatMessagePart[], isStreaming: boolean): AgentRunView {
    const run = parts.find(
      (part): part is Extract<ChatMessagePart, { type: "data-run" }> => part.type === "data-run",
    );
    const status: AgentRunStatus = run?.data.status ?? (isStreaming ? "running" : "idle");
    const steps: ActivityEntry[] = [];
    const stepById = new Map<string, ActivityEntry>();
    const sources: SourceResult[] = [];
    const sourceById = new Map<string, SourceResult>();
    let activeRetrieval: ActivityEntry | undefined;

    for (const part of parts) {
      if (part.type === "data-status") {
        const type = activityTypeFromPart(part);
        if (!type) continue;
        const id = part.data.stepId
          ?? `${type}-${part.data.toolCallId ?? legacyToolCallId(part.id) ?? steps.length}`;
        const existing = stepById.get(id);
        const nextStatus = statusFromPart(part.data.state);
        const nextStep: ActivityEntry = {
          id,
          type,
          label: part.data.label || defaultStepLabel(type, part.data.toolName),
          status: nextStatus,
          durationMs: part.data.durationMs,
          description: part.data.detail,
          toolName: part.data.toolName,
          resultCount: part.data.resultCount,
          sourceIds: existing?.sourceIds ?? [],
        };
        if (existing) {
          Object.assign(existing, {
            ...nextStep,
            description: nextStep.description ?? existing.description,
            resultCount: nextStep.resultCount ?? existing.resultCount,
          });
        } else {
          steps.push(nextStep);
          stepById.set(id, nextStep);
        }
        if (type === "knowledge_retrieval") activeRetrieval = existing ?? nextStep;
      }

      if (part.type === "data-source") {
        const source = sourceFromPart(part);
        const existing = sourceById.get(source.id);
        if (existing) {
          Object.assign(existing, source);
        } else {
          sources.push(source);
          sourceById.set(source.id, source);
        }
        if (activeRetrieval && !activeRetrieval.sourceIds.includes(source.id)) {
          activeRetrieval.sourceIds.push(source.id);
        }
      }

      if (part.type === "data-stream-error") {
        const activeGeneration = [...steps].reverse().find((step) => (
          step.status === "running"
          && (step.type === "next_step_generation"
            || step.type === "final_response_generation")
        ));
        if (activeGeneration) {
          activeGeneration.status = "failed";
          activeGeneration.description = part.data.message;
        } else {
          steps.push({
            id: `generation-error-${steps.length}`,
            type: "final_response_generation",
            label: "Generating final response",
            status: "failed",
            description: part.data.message,
            sourceIds: [],
          });
        }
      }
    }

    const hasAnswer = parts.some((part) => part.type === "text" && part.text.trim());
    const hasFinalGeneration = steps.some((step) => (
      step.type === "final_response_generation"
    ));
    if (hasAnswer && !hasFinalGeneration) {
      steps.push({
        id: "generation",
        type: "final_response_generation",
        label: status === "completed" ? "Generated final response" : "Generating final response",
        status: generationStatus(status),
        sourceIds: [],
      });
    }

    if (status === "cancelled") {
      for (const step of steps) {
        if (step.status === "running") step.status = "skipped";
      }
    }

    const reportedSourceCount = steps.reduce(
      (count, step) => count + (
        step.type === "knowledge_retrieval" ? step.resultCount ?? 0 : 0
      ),
      0,
    );
    const usedSourceCount = sources.filter((source) => source.status === "Used").length;

    return {
      status,
      startedAt: run?.data.startedAt,
      durationMs: run?.data.durationMs,
      modelDurationMs: run?.data.modelDurationMs,
      toolDurationMs: run?.data.toolDurationMs,
      toolCallCount: run?.data.toolCallCount,
      steps,
      sources,
      sourceCount: reportedSourceCount || sources.length,
      usedSourceCount,
      hasActivity: Boolean(run || steps.length || sources.length),
    };
  }
}

function generationStatus(status: AgentRunStatus): ActivityStepStatus {
  if (status === "failed") return "failed";
  if (status === "cancelled") return "skipped";
  return status === "running" ? "running" : "completed";
}

function statusFromPart(status: "active" | "completed" | "error" | "skipped"): ActivityStepStatus {
  if (status === "active") return "running";
  if (status === "error") return "failed";
  return status;
}

function defaultStepLabel(type: AgentActivityType, toolName: string | undefined) {
  if (type === "next_step_generation") return "Determining next step";
  if (type === "final_response_generation") return "Generating final response";
  if (type === "knowledge_retrieval") return "Searching knowledge base";
  if (!toolName) return "Running tool";
  return toolName.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function activityTypeFromPart(
  part: Extract<ChatMessagePart, { type: "data-status" }>,
): AgentActivityType | undefined {
  if (part.data.activityType) return part.data.activityType;
  if (part.data.phase === "retrieval") return "knowledge_retrieval";
  if (part.data.phase === "tool") return "tool_execution";
  if (part.data.phase === "model") return "final_response_generation";
  return undefined;
}

function legacyToolCallId(partId: string | undefined) {
  if (!partId) return undefined;
  return partId
    .replace(/^tool-/, "")
    .replace(/-(?:started|complete|completed)$/, "");
}

function sourceFromPart(part: Extract<ChatMessagePart, { type: "data-source" }>): SourceResult {
  const url = part.data.url;
  let domain = "Enterprise knowledge";
  if (url) {
    try {
      domain = new URL(url).hostname;
    } catch {
      // Non-HTTP source identifiers are still valid citations.
    }
  }
  const provider = providerLabel(part.data.source);
  return {
    id: part.data.id,
    title: part.data.title,
    domain,
    url,
    description: part.data.description,
    type: sourceType(part.data.source),
    provider,
    fileType: fileTypeFromTitle(part.data.title),
    relevanceScore: part.data.relevanceScore,
    status: sourceStatus(part.data.status, part.data.restricted),
  };
}

function sourceStatus(
  status: "Used" | "Found" | "Reviewed" | "Restricted" | undefined,
  restricted: boolean | undefined,
): SourceStatus {
  if (restricted) return "Restricted";
  return status ?? "Found";
}

function sourceType(source: string | undefined): SourceType {
  const normalizedSource = source?.trim().toLowerCase();
  if (normalizedSource === "jira") return "jira";
  if (normalizedSource === "confluence") return "confluence";
  if (normalizedSource === "pdf") return "pdf";
  if (normalizedSource === "database") return "database";
  if (normalizedSource === "web") return "web";
  return "document";
}

function providerLabel(source: string | undefined) {
  const value = source?.trim();
  return value ? value.replace(/[-_]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : undefined;
}

function fileTypeFromTitle(title: string) {
  const match = /\.([a-z0-9]{1,8})$/i.exec(title.trim());
  return match?.[1]?.toUpperCase();
}
