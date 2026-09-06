"use client";

import { cn } from "@/lib/cn";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: React.ReactNode;
  count?: number;
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
}

/**
 * A small mutually exclusive filter — two to five options that all fit.
 * Anything longer belongs in a Select so the control stops growing with data.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: SegmentedProps<T>) {
  return (
    <div aria-label={ariaLabel} className={cn("adm-seg", className)} role="group">
      {options.map((option) => (
        <button
          aria-pressed={option.value === value}
          className="adm-seg__item focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.icon}
          {option.label}
          {option.count !== undefined && (
            <span className="tabular-nums text-[var(--text-muted)]">{option.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
