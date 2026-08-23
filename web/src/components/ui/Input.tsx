"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { forwardRef } from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, "aria-invalid": ariaInvalid, ...props }, ref) => {
    return (
      <input
        aria-invalid={error || ariaInvalid || undefined}
        ref={ref}
        className={cn(
          ui.control,
          error && "border-[var(--danger-border)] focus:border-[var(--danger)] focus:ring-[var(--danger-soft)]",
          className
        )}
        {...props}
      />
    );
  }
);

Input.displayName = "Input";
