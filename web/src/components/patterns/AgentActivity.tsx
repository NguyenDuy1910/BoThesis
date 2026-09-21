import {
  BookOpen,
  Check,
  FileText,
  Search,
  Sparkles,
  Terminal,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/cn";

export type AgentActivityKind =
  | "analyzing"
  | "searching"
  | "reading"
  | "tool"
  | "generating"
  | "completed"
  | "failed";

const KIND: Record<AgentActivityKind, { icon: LucideIcon; iconClass: string; labelClass: string }> = {
  analyzing: { icon: Sparkles, iconClass: "text-[var(--text-tertiary)]", labelClass: "text-[var(--text-secondary)]" },
  searching: { icon: Search, iconClass: "text-[var(--text-tertiary)]", labelClass: "text-[var(--text-secondary)]" },
  reading: { icon: BookOpen, iconClass: "text-[var(--text-tertiary)]", labelClass: "text-[var(--text-secondary)]" },
  tool: { icon: Terminal, iconClass: "text-[var(--text-tertiary)]", labelClass: "text-[var(--text-secondary)]" },
  generating: { icon: FileText, iconClass: "text-[var(--text-tertiary)]", labelClass: "text-[var(--text-secondary)]" },
  completed: { icon: Check, iconClass: "text-[var(--status-success-text)]", labelClass: "text-[var(--text-tertiary)]" },
  failed: { icon: X, iconClass: "text-[var(--status-danger-text)]", labelClass: "text-[var(--text-primary)]" },
};

/**
 * What the agent is doing, in the user's language — never raw execution.
 *
 * Lines appear progressively as work happens and collapse into a single
 * Completed line once the answer lands. One text row each, never a card.
 * Failures name the consequence for the answer and offer the recovery.
 */
export function AgentActivity({
  kind,
  label,
  detail,
  action,
}: {
  kind: AgentActivityKind;
  label: string;
  detail?: string;
  /** The one recovery a failed step offers, e.g. Retry. */
  action?: React.ReactNode;
}) {
  const { icon: Icon, iconClass, labelClass } = KIND[kind];
  return (
    <div className="flex w-full items-center gap-2.5 py-[5px]">
      <Icon aria-hidden="true" className={cn("shrink-0", iconClass)} size={18} />
      <span className={cn("text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)]", labelClass)}>
        {label}
      </span>
      {detail && (
        <span className="truncate text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
          {detail}
        </span>
      )}
      <span className="flex-1" />
      {action}
    </div>
  );
}
