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
        "group transition-colors hover:bg-slate-100 active:bg-slate-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20",
        className
      )}
    >
      <div className="absolute inset-y-0 flex items-center justify-center pointer-events-none">
        <GripVertical className="h-4 w-4 text-slate-300 transition-colors group-hover:text-slate-500 group-active:text-slate-700" />
      </div>
    </div>
  );
}
