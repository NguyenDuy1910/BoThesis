import type {
  ActivityEntry,
  ActivityStepStatus,
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

    if (run || isStreaming) {
      steps.push({
        id: "planning",
        type: "planning",
        label: "Preparing response",
        status: planningStatus(status),
        sourceIds: [],
      });
    }

    for (const part of parts) {
      if (part.type === "data-status") {
        if (part.data.phase !== "tool" && part.data.phase !== "retrieval") continue;
        const type = part.data.phase;
        const id = `${type}-${part.data.toolCallId ?? legacyToolCallId(part.id) ?? steps.length}`;
        const existing = stepById.get(id);
        const nextStatus = statusFromPart(part.data.state);
        const nextStep: ActivityEntry = {
          id,
          type,
          label: displayToolName(part.data.toolName, type),
          status: nextStatus,
          durationMs: part.data.durationMs,
          description: part.data.detail,
          toolName: part.data.toolName,
          query: part.data.query,
          resultCount: part.data.resultCount,
          sourceIds: existing?.sourceIds ?? [],
        };
        if (existing) {
          Object.assign(existing, {
            ...nextStep,
            query: nextStep.query ?? existing.query,
            description: nextStep.description ?? existing.description,
            resultCount: nextStep.resultCount ?? existing.resultCount,
          });
        } else {
          steps.push(nextStep);
          stepById.set(id, nextStep);
        }
        if (type === "retrieval") activeRetrieval = existing ?? nextStep;
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
        steps.push({
          id: `generation-error-${steps.length}`,
          type: "generation",
          label: "Generating answer",
          status: "failed",
          description: part.data.message,
          sourceIds: [],
        });
      }
    }

    const hasAnswer = parts.some((part) => part.type === "text" && part.text.trim());
    if (hasAnswer) {
      steps.push({
        id: "generation",
        type: "generation",
        label: "Generating answer",
        status: generationStatus(status),
        sourceIds: [],
      });
    }

    if (status === "completed") {
      steps.push({
        id: "completion",
        type: "completion",
        label: "Answer ready",
        status: "completed",
        sourceIds: [],
      });
    }

    if (status === "cancelled") {
      steps.push({
        id: "cancelled",
        type: "completion",
        label: "Run cancelled",
        status: "skipped",
        sourceIds: [],
      });
    }

    const planningStep = steps.find((step) => step.id === "planning");
    if (planningStep && planningStep.status !== "skipped" && steps.length > 1) {
      planningStep.status = "completed";
    }

    const reportedSourceCount = steps.reduce(
      (count, step) => count + (step.type === "retrieval" ? step.resultCount ?? 0 : 0),
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

function planningStatus(status: AgentRunStatus): ActivityStepStatus {
  if (status === "failed") return "failed";
  if (status === "cancelled") return "skipped";
  return status === "running" ? "running" : "completed";
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

function displayToolName(toolName: string | undefined, type: "tool" | "retrieval") {
  if (toolName === "knowledge_search" || type === "retrieval") return "Search knowledge base";
  if (!toolName) return "Run tool";
  return toolName.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
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
