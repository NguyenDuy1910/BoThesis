"use client";

import { ChevronDown } from "lucide-react";
import { forwardRef } from "react";

import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  error?: boolean;
  options: { value: string; label: string }[];
  placeholder?: string;
  className?: string;
}

/**
 * A native select, wrapped so it carries the same chevron affordance as every
 * other menu-like control. Without it the field reads as a text input.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, error, options, placeholder, "aria-invalid": ariaInvalid, ...props },
  ref,
) {
  return (
    <div className={cn("relative inline-flex w-full", className)}>
      <select
        aria-invalid={error || ariaInvalid || undefined}
        className={cn(ui.control, "cursor-pointer appearance-none pr-8")}
        ref={ref}
        {...props}
      >
        {placeholder && (
          <option disabled value="">
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]"
      />
    </div>
  );
});
