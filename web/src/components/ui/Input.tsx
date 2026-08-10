"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { forwardRef } from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          ui.control,
          error && "border-red-300 focus:border-red-300 focus:ring-red-200",
          className
        )}
        {...props}
      />
    );
  }
);

Input.displayName = "Input";
