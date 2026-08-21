"use client";

import { cn } from "@/lib/cn";
import { GripVertical } from "lucide-react";

interface ResizeHandleProps {
  onPointerDown: (e: React.PointerEvent) => void;
  onDoubleClick: () => void;
  className?: string;
}

export function ResizeHandle({ onPointerDown, onDoubleClick, className }: ResizeHandleProps) {
  return (
    <div
      role="separator"
      aria-label="Resize panel"
      aria-orientation="vertical"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter") onDoubleClick();
      }}
      className={cn(
        "relative flex w-1.5 cursor-col-resize items-center justify-center shrink-0",
        "before:absolute before:inset-y-0 before:-left-1 before:-right-1",
        "group transition-colors hover:bg-[var(--surface-hover)] active:bg-[var(--surface-selected)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
        className
      )}
    >
      <div className="absolute inset-y-0 flex items-center justify-center pointer-events-none">
        <GripVertical aria-hidden="true" className="h-4 w-4 text-[var(--border-strong)] transition-colors group-hover:text-[var(--text-muted)] group-active:text-[var(--text-secondary)]" />
      </div>
    </div>
  );
}
