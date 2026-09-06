"use client";

import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";

interface FormFieldProps {
  label: string;
  htmlFor?: string;
  /** What the value is for, in plain language. Shown until an error replaces it. */
  helperText?: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

export function FormField({
  label,
  htmlFor,
  helperText,
  error,
  required,
  children,
  className,
}: FormFieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label className={cn("block", ui.label)} htmlFor={htmlFor}>
        {label}
        {!required && (
          <span className="ml-1.5 font-normal text-[var(--text-muted)]">Optional</span>
        )}
      </label>
      {children}
      {error ? (
        <p
          className={ui.errorText}
          id={htmlFor ? `${htmlFor}-error` : undefined}
          role="alert"
        >
          {error}
        </p>
      ) : (
        helperText && (
          <p className={ui.helper} id={htmlFor ? `${htmlFor}-helper` : undefined}>
            {helperText}
          </p>
        )
      )}
    </div>
  );
}

/**
 * Groups related fields under one heading so a long form reads as a few
 * decisions rather than a list of inputs.
 */
export function FormSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className={ui.sectionTitle}>{title}</legend>
      {description && <p className={ui.sectionDescription}>{description}</p>}
      <div className="mt-3 space-y-3.5">{children}</div>
    </fieldset>
  );
}
