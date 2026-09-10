"use client";

import clsx from "clsx";
import { Check, ChevronRight, Circle, CircleAlert, Terminal } from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";

import { assistantTurnItems } from "../assistant-turn";
import type { AnswerSource } from "../sources";
import type { HostedExecutionOutput, RuntimeActivity, TurnState } from "../types";
import {
  CitationRenderingProvider,
  citationRenderingSources,
  IncrementalMarkdown,
} from "./IncrementalMarkdown";

export const AssistantTurn = memo(function AssistantTurn({
  activeCitationId,
  isStreaming,
  onOpenSource,
  onRevealingChange,
  sources,
  turn,
}: {
  activeCitationId?: string;
  isStreaming: boolean;
  onOpenSource?: (source: AnswerSource) => void;
  /** Report while the turn's newest text is still easing onto screen. */
  onRevealingChange?: (isRevealing: boolean) => void;
  /** The citations this answer produced, for the inline chips. */
  sources?: readonly AnswerSource[];
  turn?: TurnState;
}) {
  const items = assistantTurnItems(turn);
  const pending = Boolean(isStreaming && turn?.modelPending);
  const { visible: showPending } = usePendingIndicator(pending);
  const revealingItemId = items.filter((item) => item.kind === "message").at(-1)?.id;
  const citations = useMemo(() => ({
    sources: citationRenderingSources(sources ?? []),
    activeCitationId,
    onOpenSource,
  }), [activeCitationId, onOpenSource, sources]);

  if (!items.length && !showPending) return null;

  return (
    <CitationRenderingProvider value={citations}>
      <div className="assistant-turn">
        {items.map((item) => {
          if (item.kind === "message") {
            return (
              <div
                className={clsx("assistant-content", item.phase === "commentary" && "assistant-content--commentary")}
                data-assistant-phase={item.phase}
                key={item.id}
              >
                <IncrementalMarkdown
                  isStreaming={isStreaming && item.state === "streaming"}
                  onRevealingChange={item.id === revealingItemId ? onRevealingChange : undefined}
                  text={item.text}
                />
              </div>
            );
          }
          if (item.kind === "activity") {
            return <ToolActivity activity={item.activity} key={item.id} />;
          }
          return <HostedExecutionActivity execution={item} key={item.id} />;
        })}
        {showPending && (
          <span aria-label="BoThesis is working" className="assistant-turn__pending" role="status">BoThesis</span>
        )}
      </div>
    </CitationRenderingProvider>
  );
});

function usePendingIndicator(pending: boolean) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!pending) {
      setVisible(false);
      return;
    }
    const timeout = window.setTimeout(() => setVisible(true), 700);
    return () => window.clearTimeout(timeout);
  }, [pending]);
  return { visible: pending && visible };
}

function HostedExecutionActivity({
  execution,
}: {
  execution: Extract<ReturnType<typeof assistantTurnItems>[number], { kind: "execution" }>;
}) {
  const active = execution.state === "running";
  const failed = execution.state === "failed" || execution.state === "timeout";
  const command = execution.commands.join("\n");
  const output = formatExecutionOutput(execution.output);
  const label = active
    ? "Running hosted shell"
    : execution.state === "timeout"
      ? "Hosted shell timed out"
      : execution.state === "failed"
        ? "Hosted shell finished with an error"
        : "Hosted shell completed";
  const Icon = active ? Circle : failed ? CircleAlert : Check;

  return (
    <details
      className={clsx("assistant-turn__execution", `assistant-turn__execution--${execution.state}`)}
      open={active || failed}
    >
      <summary aria-label={`${label}${command ? `: ${command}` : ""}`}>
        <Icon aria-hidden="true" className="assistant-turn__execution-status" size={14} />
        <Terminal aria-hidden="true" className="assistant-turn__execution-terminal" size={15} />
        <span className="assistant-turn__execution-label">{label}</span>
        {command && <code className="assistant-turn__execution-command">{command}</code>}
        <ChevronRight aria-hidden="true" className="assistant-turn__execution-caret" size={15} />
      </summary>
      <div className="assistant-turn__execution-body">
        {command && <pre aria-label="Executed command"><code>{command}</code></pre>}
        {output && <pre aria-label="Command output"><code>{output}</code></pre>}
        {execution.files.length > 0 && (
          <p className="assistant-turn__execution-files" role="status">
            Files reported: {execution.files.join(", ")}
          </p>
        )}
        {!output && !active && <p>No command output was returned.</p>}
      </div>
    </details>
  );
}

function formatExecutionOutput(output: HostedExecutionOutput[]) {
  return output.map((entry, index) => {
    const status = entry.timed_out
      ? "Timed out"
      : `Exit code: ${entry.exit_code ?? "unknown"}`;
    const text = [entry.stdout, entry.stderr].filter(Boolean).join("\n");
    return `${output.length > 1 ? `Command ${index + 1} · ` : ""}${status}${text ? `\n${text}` : ""}`;
  }).join("\n\n");
}

function ToolActivity({ activity }: { activity: RuntimeActivity }) {
  const presentation = toolPresentation(activity);
  const active = activity.state === "active";
  const error = activity.state === "failed" || activity.state === "timeout";
  const elapsed = useElapsedSeconds(activity.startedAt, active);
  const Icon = active ? Circle : error ? CircleAlert : Check;
  const elapsedLabel = active && elapsed >= 10 ? `${elapsed}s` : undefined;
  const accessibleLabel = [presentation.label, presentation.detail, elapsedLabel]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      aria-label={accessibleLabel}
      className={clsx("assistant-turn__activity", `assistant-turn__activity--${activity.state}`)}
      role={active ? "status" : undefined}
      title={accessibleLabel}
    >
      <Icon aria-hidden="true" className="assistant-turn__activity-icon" size={13} />
      <span className="assistant-turn__activity-label">{presentation.label}</span>
      {presentation.detail && <span className="assistant-turn__activity-detail">· {presentation.detail}</span>}
      {elapsedLabel && <time>· {elapsedLabel}</time>}
    </div>
  );
}

function useElapsedSeconds(startedAt: number, active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);
  return Math.max(0, Math.floor((now - startedAt) / 1_000));
}

function toolPresentation(activity: RuntimeActivity) {
  const active = activity.state === "active";
  const progressCount = numericProgress(activity.progress, "result_count");
  const resultCount = activity.resultCount ?? progressCount;
  const vocabulary: Record<string, { active: string; completed: string; showResultCount?: boolean }> = {
    knowledge_search: { active: "Đang tìm tài liệu liên quan…", completed: "Đã tìm tài liệu liên quan", showResultCount: true },
    read_resource: { active: "Đang đọc tài liệu…", completed: "Đã đọc tài liệu" },
    inspect_resource: { active: "Đang kiểm tra tài liệu…", completed: "Đã kiểm tra tài liệu" },
    materialize_resource: { active: "Đang chuẩn bị tài liệu…", completed: "Đã chuẩn bị tài liệu" },
    materialize_sandbox_resource: { active: "Đang chuẩn bị tệp cho không gian làm việc…", completed: "Tệp đã sẵn sàng trong không gian làm việc" },
    export_sandbox_file: { active: "Đang lưu tệp từ không gian làm việc…", completed: "Đã lưu tệp để dùng lại" },
    document_edit: { active: "Đang chỉnh sửa tài liệu…", completed: "Đã chỉnh sửa tài liệu" },
    artifact_create: { active: "Đang hoàn thiện tài liệu…", completed: "Đã tạo tài liệu" },
  };
  const text = vocabulary[activity.toolName] ?? {
    active: "Đang xử lý yêu cầu…",
    completed: "Đã hoàn tất thao tác",
  };
  if (activity.state === "failed") return { label: "Không thể hoàn tất thao tác", detail: undefined };
  if (activity.state === "timeout") return { label: "Thao tác mất quá nhiều thời gian", detail: undefined };
  if (activity.state === "skipped") return { label: "Đã bỏ qua thao tác", detail: undefined };
  return {
    label: active ? text.active : text.completed,
    detail: !active && text.showResultCount && resultCount !== undefined
      ? `${resultCount} tài liệu`
      : undefined,
  };
}

function numericProgress(progress: Record<string, unknown> | undefined, key: string) {
  const value = progress?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
