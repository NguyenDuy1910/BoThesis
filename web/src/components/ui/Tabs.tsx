"use client";

import { useId, useRef } from "react";

import { cn } from "@/lib/cn";

interface Tab {
  id: string;
  label: string;
  /** Only ever a count someone can act on — never a total for decoration. */
  count?: number;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
  density?: "default" | "compact";
  ariaLabel?: string;
  idBase?: string;
}

/**
 * Page-level tabs: the subviews of the destination you are already in.
 *
 * The navigation rail owns destinations and never changes when one of these is
 * pressed — the Figma behaviour spec states it directly ("Change the child
 * route in main content; sidebar remains unchanged"), which is why domain
 * subviews live here instead of expanding a tree in the rail.
 *
 * Selected state is the same tinted pill the rail uses for its own selection,
 * minus the leading accent rule. That rule is reserved for the one active
 * top-level destination, so a tinted tab can never be mistaken for one.
 */
export function Tabs({
  tabs,
  activeTab,
  onChange,
  className,
  density = "default",
  ariaLabel = "Tabs",
  idBase,
}: TabsProps) {
  const compact = density === "compact";
  const tabsId = useId();
  const listRef = useRef<HTMLDivElement | null>(null);

  const focusTab = (index: number) => {
    const target = (index + tabs.length) % tabs.length;
    listRef.current
      ?.querySelectorAll<HTMLButtonElement>("[role='tab']")
      [target]?.focus();
  };

  return (
    <div
      aria-label={ariaLabel}
      className={cn("flex gap-1 overflow-x-auto", className)}
      ref={listRef}
      role="tablist"
    >
      {tabs.map((tab, index) => {
        const selected = activeTab === tab.id;
        return (
          <button
            aria-controls={idBase ? `${idBase}-${tab.id}-panel` : undefined}
            aria-selected={selected}
            className={cn(
              "shrink-0 rounded-[var(--radius-sm)] font-medium",
              "transition-colors duration-[var(--duration-fast)] ease-[var(--ease-out)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-base)]",
              compact
                ? "h-8 px-2.5 text-[length:var(--text-size-ui)]"
                : "h-9 px-3 text-[length:var(--text-size-nav)]",
              selected
                ? "bg-[var(--surface-selected)] text-[var(--text-accent)]"
                : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
            )}
            id={idBase ? `${idBase}-${tab.id}` : `${tabsId}-${tab.id}`}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => {
              // Arrow keys move focus; Enter or Space commits. Selecting a tab
              // changes the route and refetches, so arrowing across the row
              // must not fire four navigations on the way past.
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                focusTab(index - 1);
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                focusTab(index + 1);
              } else if (event.key === "Home") {
                event.preventDefault();
                focusTab(0);
              } else if (event.key === "End") {
                event.preventDefault();
                focusTab(tabs.length - 1);
              }
            }}
            role="tab"
            // Roving tabindex: one stop for the whole row, and if focus is
            // resting on a tab that is not the selected one, that tab keeps
            // the stop so arrowing away and back is not a trap.
            tabIndex={selected ? 0 : -1}
            type="button"
          >
            <span className="inline-flex h-full items-center gap-1.5">
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span
                  className={cn(
                    "rounded-[var(--radius-full)] px-1.5 py-0.5 text-[length:var(--text-size-caption)] font-medium leading-none",
                    selected
                      ? "bg-[var(--accent-soft-hover)] text-[var(--text-accent)]"
                      : "bg-[var(--surface-subtle)] text-[var(--text-tertiary)]",
                  )}
                >
                  {tab.count}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
