import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * Non-blocking setup guidance after a tenant is created.
 *
 * Order is a suggestion, never a gate — any step may be done at any time, and
 * the whole checklist can be dismissed.
 */
export function ChecklistItem({ label, done = false }: { label: string; done?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 py-2">
      {done ? (
        <Check aria-hidden="true" className="shrink-0 text-[var(--status-success-text)]" size={18} />
      ) : (
        <span
          aria-hidden="true"
          className="h-[15px] w-[15px] shrink-0 rounded-full border-[1.25px] border-[var(--border-default)]"
        />
      )}
      <span
        className={cn(
          "min-w-0 flex-1 truncate text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)]",
          done ? "text-[var(--text-tertiary)]" : "text-[var(--text-primary)]",
        )}
      >
        {label}
      </span>
    </div>
  );
}
