import { cn } from "@/lib/cn";

/**
 * The LLM pending treatment.
 *
 * A 1.6s sweep travels across the BoThesis wordmark and repeats. Never a
 * spinner and never an ellipsis: this says the agent is working, not that the
 * page is loading. `label` adds the current activity in plain language.
 */
export function ThinkingIndicator({ label, className }: { label?: string; className?: string }) {
  return (
    <p aria-live="polite" className={cn("flex items-center gap-2 py-1", className)}>
      <span className="bothesis-thinking text-[length:var(--text-size-body)] font-medium leading-[var(--text-lh-body)]">
        BoThesis
      </span>
      {label && (
        <>
          <span aria-hidden="true" className="text-[var(--text-tertiary)]">
            ·
          </span>
          <span className="text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-tertiary)]">
            {label}
          </span>
        </>
      )}
    </p>
  );
}
