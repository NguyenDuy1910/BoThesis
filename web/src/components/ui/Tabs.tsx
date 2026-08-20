"use client";

import { cn } from "@/lib/cn";

interface Tab {
  id: string;
  label: string;
  count?: number;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
  density?: "default" | "compact";
}

export function Tabs({ tabs, activeTab, onChange, className, density = "default" }: TabsProps) {
  const compact = density === "compact";

  return (
    <div className={cn("border-b border-slate-200", className)}>
      <nav className="flex gap-4 overflow-x-auto" aria-label="Tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            aria-selected={activeTab === tab.id}
            role="tab"
            className={cn(
              "relative -mb-px shrink-0 border-b-2 border-transparent font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
              compact ? "h-8 px-0.5 text-xs" : "h-10 px-0.5 text-sm",
              activeTab === tab.id
                ? "border-teal-600 text-teal-700"
                : "text-slate-500 hover:border-slate-300 hover:text-slate-700"
            )}
          >
            <span className="inline-flex h-full items-center gap-1.5">
              {tab.label}
              {tab.count !== undefined && (
                <span className={cn(
                  "rounded-full px-1.5 py-0.5 text-[11px] leading-none",
                  activeTab === tab.id ? "bg-teal-50 text-teal-700" : "bg-slate-100 text-slate-500"
                )}>
                  {tab.count}
                </span>
              )}
            </span>
          </button>
        ))}
      </nav>
    </div>
  );
}
