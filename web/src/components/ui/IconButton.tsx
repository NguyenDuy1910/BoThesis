"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

type IconButtonVariant = "ghost" | "secondary" | "danger" | "primary";
type IconButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<IconButtonVariant, string> = {
  ghost: "border border-transparent text-[var(--text-tertiary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
  secondary:
    "border border-[var(--border-subtle)] bg-[var(--surface-base)] text-[var(--text-tertiary)] hover:border-[var(--border-default)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
  danger: "border border-transparent text-[var(--text-tertiary)] hover:bg-[var(--status-danger-bg)] hover:text-[var(--status-danger-solid)]",
  primary: "border border-[var(--accent-primary)] bg-[var(--accent-primary)] text-[var(--text-on-accent)] hover:bg-[var(--accent-hover)]",
};

const sizeClasses: Record<IconButtonSize, string> = {
  sm: "h-8 w-8 rounded-md",
  md: "h-9 w-9 rounded-md",
  lg: "h-10 w-10 rounded-md",
};

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  loading?: boolean;
}

export function IconButton({
  label,
  variant = "ghost",
  size = "md",
  loading = false,
  children,
  className,
  disabled,
  type = "button",
  ...props
}: IconButtonProps) {
  return (
    <button
      aria-busy={loading || undefined}
      aria-label={label}
      title={props.title ?? label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center transition-[background-color,border-color,color,box-shadow,opacity] duration-[var(--duration-base)] ease-[var(--ease-out)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-base)]",
        "disabled:pointer-events-none disabled:border-[var(--border-subtle)] disabled:bg-[var(--surface-subtle)] disabled:text-[var(--text-tertiary)] disabled:opacity-50 disabled:shadow-none",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : children}
    </button>
  );
}
