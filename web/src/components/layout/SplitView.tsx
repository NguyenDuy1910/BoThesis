"use client";

import { cn } from "@/lib/cn";

/**
 * A stable list/detail frame. The owner keeps selection, filters, and scroll
 * state; changing mode only changes which pane is visible.
 */
export type SplitViewMode = "list" | "split" | "detail";

export function SplitView({
  mode,
  list,
  detail,
  className,
}: {
  mode: SplitViewMode;
  list: React.ReactNode;
  detail: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "document-split",
        className,
      )}
      data-mode={mode}
    >
      <section
        aria-label="Document list"
        className={cn(
          "min-h-0 overflow-y-auto",
          mode === "detail" && "hidden",
          mode === "split" && "border-r border-[var(--border-subtle)]",
        )}
      >
        {list}
      </section>
      <section
        aria-label="Selected document"
        className={cn("min-h-0 overflow-y-auto", mode === "list" && "hidden")}
      >
        {detail}
      </section>
    </div>
  );
}
