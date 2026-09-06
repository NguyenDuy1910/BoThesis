"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { forwardRef } from "react";

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, "aria-invalid": ariaInvalid, ...props }, ref) => {
    return (
      <textarea
        aria-invalid={error || ariaInvalid || undefined}
        ref={ref}
        className={cn(ui.textarea, className)}
        {...props}
      />
    );
  }
);

Textarea.displayName = "Textarea";
