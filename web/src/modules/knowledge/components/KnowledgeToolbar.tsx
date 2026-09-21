"use client";

import { Check } from "lucide-react";

import { Dropdown, DropdownItem } from "@/components/ui/Dropdown";
import { SearchInput } from "@/components/ui/SearchInput";
import { Tabs } from "@/components/ui/Tabs";

export const knowledgeTabs = [
  { id: "documents", label: "Documents" },
  { id: "sources", label: "Sources" },
  { id: "activity", label: "Sync activity" },
] as const;

export type KnowledgeTab = (typeof knowledgeTabs)[number]["id"];

/**
 * The one line Knowledge is operated from.
 *
 * Where you are (the three subviews), what you are looking at (scope), how you
 * narrow it (search) and what you do to it (the quiet icon controls) share a
 * single strip. Splitting them into a tab row and a filter row below spends
 * two bands of the page on navigation that fits in one, and makes the scope
 * read as a property of the page rather than of the list.
 */
export function KnowledgeToolbar({
  tab,
  onTabChange,
  scope,
  search,
  actions,
}: {
  tab: KnowledgeTab;
  onTabChange: (tab: string) => void;
  /** Only Documents is browsed by scope; the other two subviews omit it. */
  scope?: React.ReactNode;
  search: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    label: string;
  };
  actions?: React.ReactNode;
}) {
  return (
    <div className="knowledge-bar">
      <Tabs
        activeTab={tab}
        ariaLabel="Knowledge views"
        className="knowledge-bar__tabs"
        onChange={onTabChange}
        tabs={knowledgeTabs.slice()}
        variant="underline"
      />
      <div className="knowledge-bar__utilities">
        {scope}
        <SearchInput
          ariaLabel={search.label}
          className="knowledge-bar__search"
          debounceMs={120}
          onChange={search.onChange}
          placeholder={search.placeholder}
          value={search.value}
        />
        {actions && <div className="knowledge-bar__actions">{actions}</div>}
      </div>
    </div>
  );
}

export interface ScopeOption {
  value: string;
  label: string;
  /** Shown beside the name in the menu; never on the trigger. */
  detail?: string;
  disabled?: boolean;
}

/**
 * Where the reader is browsing.
 *
 * This is the only place scope is stated. A breadcrumb above the list would
 * say the same thing a second time, and the search field's placeholder a
 * third — so both stay generic and this control carries it alone.
 */
export function KnowledgeScopeSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: readonly ScopeOption[];
  onChange: (value: string) => void;
}) {
  const active = options.find((option) => option.value === value) ?? options[0];
  return (
    <Dropdown
      align="left"
      ariaLabel="Knowledge scope"
      buttonClassName="knowledge-scope-trigger"
      className="shrink-0"
      label={<span className="truncate">{active?.label}</span>}
      menuClassName="min-w-60"
    >
      {options.map((option) => (
        <DropdownItem
          disabled={option.disabled}
          key={option.value || "all"}
          onClick={() => onChange(option.value)}
          selected={option.value === value}
        >
          <Check
            aria-hidden="true"
            className={option.value === value ? "h-3.5 w-3.5 shrink-0" : "h-3.5 w-3.5 shrink-0 opacity-0"}
          />
          <span className="min-w-0 flex-1 truncate">{option.label}</span>
          {option.detail && (
            <span className="shrink-0 text-[length:var(--text-size-meta)] font-normal text-[var(--text-tertiary)]">
              {option.detail}
            </span>
          )}
        </DropdownItem>
      ))}
    </Dropdown>
  );
}
