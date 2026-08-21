"use client";

import { cn } from "@/lib/cn";
import { useId } from "react";

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
  const tabsId = useId();

  return (
    <div className={cn("border-b border-[var(--border)]", className)}>
      <div aria-label="Tabs" className="flex gap-4 overflow-x-auto" role="tablist">
        {tabs.map((tab, index) => (
          <button
            id={`${tabsId}-${tab.id}`}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => {
              const keyTargets = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: tabs.length - 1 } as const;
              if (!(event.key in keyTargets)) return;
              event.preventDefault();
              const rawTarget = keyTargets[event.key as keyof typeof keyTargets];
              const target = (rawTarget + tabs.length) % tabs.length;
              onChange(tabs[target].id);
              event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']")[target]?.focus();
            }}
            aria-selected={activeTab === tab.id}
            role="tab"
            tabIndex={activeTab === tab.id ? 0 : -1}
            type="button"
            className={cn(
              "relative -mb-px shrink-0 border-b-2 border-transparent font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]",
              compact ? "h-8 px-0.5 text-xs" : "h-10 px-0.5 text-sm",
              activeTab === tab.id
                ? "border-[var(--brand-accent)] text-[var(--brand-accent)]"
                : "text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]"
            )}
          >
            <span className="inline-flex h-full items-center gap-1.5">
              {tab.label}
              {tab.count !== undefined && (
                <span className={cn(
                  "rounded-full px-1.5 py-0.5 text-[11px] leading-none",
                  activeTab === tab.id ? "bg-[var(--primary-soft)] text-[var(--brand-accent)]" : "bg-[var(--bg-subtle)] text-[var(--text-muted)]"
                )}>
                  {tab.count}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
