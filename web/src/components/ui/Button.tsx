"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";
import { forwardRef } from "react";

/**
 * One action hierarchy for the whole product.
 *
 * primary      one per screen — the action the page exists for
 * secondary    outlined; supporting actions of equal weight to each other
 * tertiary     soft fill; toolbar and inline actions that must not compete
 * ghost        chromeless; row actions, icon actions, dismissals
 * destructive  solid red; only inside a confirmation, never on a list row
 * danger       outlined red; the row-level entry point into a destructive flow
 */
export type ButtonVariant =
  | "primary"
  | "secondary"
  | "tertiary"
  | "ghost"
  | "destructive"
  | "danger";

export type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--accent-primary)] text-[var(--text-on-accent)] shadow-[var(--elevation-1)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-pressed)]",
  secondary:
    "bg-[var(--surface-base)] text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--border-default)] hover:bg-[var(--surface-inset)] hover:text-[var(--text-primary)] hover:shadow-[inset_0_0_0_1px_var(--border-default)] active:bg-[var(--surface-hover)]",
  tertiary:
    "bg-[var(--surface-inset)] text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--border-subtle)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]",
  ghost:
    "text-[var(--text-tertiary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] active:bg-[var(--surface-selected)]",
  destructive:
    "bg-[var(--status-danger-solid)] text-white shadow-[var(--elevation-1)] hover:brightness-95 active:brightness-90",
  danger:
    "bg-transparent text-[var(--status-danger-text)] shadow-[inset_0_0_0_1px_var(--status-danger-border)] hover:bg-[var(--status-danger-bg)]",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-[var(--radius-sm)] px-2.5 text-[length:var(--text-size-ui)]",
  md: "h-9 gap-1.5 rounded-[var(--radius-sm)] px-3 text-[length:var(--text-size-ui)]",
  lg: "h-10 gap-2 rounded-[var(--radius-md)] px-4 text-sm",
};

const iconOnlySizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 w-8 rounded-[var(--radius-sm)] px-0",
  md: "h-9 w-9 rounded-[var(--radius-sm)] px-0",
  lg: "h-10 w-10 rounded-[var(--radius-md)] px-0",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
  iconAfter?: React.ReactNode;
  /** Renders a square control. Pass `aria-label` — the label is not visible. */
  iconOnly?: boolean;
  selected?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    icon,
    iconAfter,
    iconOnly = false,
    selected,
    children,
    className,
    disabled,
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium leading-none",
        "transition-[background-color,color,box-shadow,opacity] duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-canvas)]",
        "disabled:pointer-events-none disabled:opacity-45",
        variantClasses[variant],
        iconOnly ? iconOnlySizeClasses[size] : sizeClasses[size],
        selected &&
          variant !== "primary" &&
          "bg-[var(--surface-selected)] text-[var(--text-accent)]",
        className,
      )}
      disabled={disabled || loading}
      type={type}
      title={iconOnly ? props["aria-label"] : undefined}
      {...props}
    >
      {loading ? (
        <Loader2 aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin" />
      ) : (
        icon
      )}
      {!iconOnly && children}
      {!iconOnly && !loading && iconAfter}
    </button>
  );
});
