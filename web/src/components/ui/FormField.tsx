"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";

interface FormFieldProps {
  label: string;
  htmlFor?: string;
  helperText?: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function FormField({ label, htmlFor, helperText, error, required, children, className }: FormFieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className={cn("block", ui.label)}>
        {label}
        {required && <span aria-hidden="true" className="ml-0.5 text-[var(--danger)]">*</span>}
      </label>
      {children}
      {helperText && !error && <p className={ui.helper} id={htmlFor ? `${htmlFor}-helper` : undefined}>{helperText}</p>}
      {error && <p className="text-sm leading-5 text-[var(--danger)]" id={htmlFor ? `${htmlFor}-error` : undefined} role="alert">{error}</p>}
    </div>
  );
}
