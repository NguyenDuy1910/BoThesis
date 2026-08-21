"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "border border-[var(--primary)] bg-[var(--primary)] text-[var(--text-on-brand)] hover:border-[var(--primary-hover)] hover:bg-[var(--primary-hover)] active:opacity-90",
  secondary:
    "border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-panel)] hover:text-[var(--text)] active:bg-[var(--surface-selected)]",
  ghost:
    "border border-transparent text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] active:bg-[var(--surface-selected)]",
  danger:
    "border border-[var(--danger-border)] bg-[var(--surface)] text-[var(--danger)] hover:bg-[var(--danger-soft)] active:opacity-85",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-md px-2.5 text-sm",
  md: "h-9 gap-2 rounded-md px-3 text-sm",
  lg: "h-10 gap-2 rounded-md px-3.5 text-sm",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
  selected?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  selected,
  children,
  className,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium leading-none transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface)]",
        "disabled:pointer-events-none disabled:border-[var(--border)] disabled:bg-[var(--bg-subtle)] disabled:text-[var(--text-muted)] disabled:opacity-50 disabled:shadow-none",
        variantClasses[variant],
        sizeClasses[size],
        selected && variant !== "primary" && "border-[var(--border-strong)] bg-[var(--surface-selected)] text-[var(--brand-accent)]",
        className
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />}
      {!loading && icon}
      {children}
    </button>
  );
}
