"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { forwardRef } from "react";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  error?: boolean;
  options: { value: string; label: string }[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, error, options, placeholder, "aria-invalid": ariaInvalid, ...props }, ref) => {
    return (
      <select
        aria-invalid={error || ariaInvalid || undefined}
        ref={ref}
        className={cn(
          ui.control,
          "appearance-none pr-8",
          error && "border-[var(--danger-border)] focus:border-[var(--danger)] focus:ring-[var(--danger-soft)]",
          className
        )}
        {...props}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  }
);

Select.displayName = "Select";
