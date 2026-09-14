"use client";

import { MoreHorizontal, ChevronDown } from "lucide-react";

import { Dropdown } from "@/components/ui/Dropdown";
import { SearchInput } from "@/components/ui/SearchInput";

/**
 * The command bar that opens every collection screen.
 *
 * It replaces the page title and standfirst that used to sit here. The
 * navigation rail and the breadcrumb already say where you are; repeating it
 * as a heading spends the most valuable strip of the page on something the
 * reader already knows. What belongs here is what a person does to the
 * collection: find, narrow, see how much there is, and act.
 *
 *   search ─ filters ──────────────── count · overflow · primary action
 *
 * The count sits with the actions rather than floating mid-bar, so the bar
 * reads as two groups — narrow the set on the left, act on it on the right.
 */

interface CommandBarProps {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    /** Names the field for assistive technology; there is no visible label. */
    label: string;
  };
  /** Selects and toggles that narrow the collection. */
  filters?: React.ReactNode;
  /**
   * How many objects the current search and filters yield, already worded
   * ("24 people", "126 workspaces"). A count is only shown when it is the
   * result of something — never as decoration.
   */
  count?: string;
  /** Lower-priority actions. They live in the overflow menu at every width. */
  overflow?: React.ReactNode;
  /** At most one. The action the screen exists for. */
  action?: React.ReactNode;
}

export function CommandBar({
  search,
  filters,
  count,
  overflow,
  action,
}: CommandBarProps) {
  return (
    <div className="utility-bar">
      {search && <SearchInput ariaLabel={search.label} className="utility-bar__search" debounceMs={0} onChange={search.onChange} placeholder={search.placeholder} value={search.value} />}

      {filters && <div className="flex shrink-0 items-center gap-1">{filters}</div>}

      <div className="ml-auto flex items-center gap-2">
        {count && (
          <span className="whitespace-nowrap text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
            {count}
          </span>
        )}
        {overflow && (
          <Dropdown
            align="right"
            ariaLabel="More actions"
            buttonClassName="h-[var(--control-h-md)] w-9 justify-center px-0"
            label={<MoreHorizontal aria-hidden="true" className="h-4 w-4" />}
            showChevron={false}
          >
            {overflow}
          </Dropdown>
        )}
        {action}
      </div>
    </div>
  );
}

/**
 * A collection and the inspector that describes its selection.
 *
 * Above `--bp-inspector` they sit side by side; below, `Inspector` puts itself
 * over the collection as a drawer, so this only has to stop reserving the
 * column. Nothing here knows what the objects are.
 */
export function CollectionLayout({
  children,
  inspector,
}: {
  children: React.ReactNode;
  inspector?: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-start gap-4">
      <div className="min-w-0 flex-1">{children}</div>
      {inspector}
    </div>
  );
}

/** Quiet filter/sort control for the shared utility bar. */
export function FilterTrigger({ label, value, onChange, options }: {
  label: string; value: string; onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
}) {
  return <label className="utility-filter">
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
    <ChevronDown aria-hidden="true" size={14} />
  </label>;
}
