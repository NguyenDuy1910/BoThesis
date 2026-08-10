"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { forwardRef } from "react";

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          ui.textarea,
          error && "border-red-300 focus:border-red-300 focus:ring-red-200",
          className
        )}
        {...props}
      />
    );
  }
);

Textarea.displayName = "Textarea";
