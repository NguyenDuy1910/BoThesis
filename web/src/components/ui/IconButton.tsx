"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

type IconButtonVariant = "ghost" | "secondary" | "danger" | "primary";
type IconButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<IconButtonVariant, string> = {
  ghost: "border border-transparent text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
  secondary:
    "border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
  danger: "border border-transparent text-[var(--text-muted)] hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]",
  primary: "border border-[var(--primary)] bg-[var(--primary)] text-[var(--text-on-brand)] hover:bg-[var(--primary-hover)]",
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
        "inline-flex shrink-0 items-center justify-center transition-[background-color,border-color,color,box-shadow,opacity] duration-[var(--duration-base)] ease-[var(--ease-standard)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface)]",
        "disabled:pointer-events-none disabled:border-[var(--border)] disabled:bg-[var(--bg-subtle)] disabled:text-[var(--text-muted)] disabled:opacity-50 disabled:shadow-none",
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
