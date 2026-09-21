"use client";

import { Loader2 } from "lucide-react";
import { forwardRef } from "react";

import { cn } from "@/lib/cn";

export type ChatButtonTone =
  | "primary"
  | "secondary"
  | "soft"
  | "ghost"
  | "success"
  | "warning"
  | "danger"
  | "contextual";

export type ChatButtonSize = "m" | "l";

const toneClasses: Record<ChatButtonTone, string> = {
  primary: "bg-[var(--action-primary-bg)] text-[var(--text-on-action)] shadow-[var(--elevation-2)] hover:bg-[var(--action-primary-hover)] active:bg-[var(--action-primary-pressed)]",
  secondary: "bg-[var(--surface-base)] text-[var(--text-primary)] shadow-[inset_0_0_0_1px_var(--border-default)] hover:bg-[var(--surface-hover)] active:bg-[var(--surface-selected)]",
  soft: "bg-[var(--surface-subtle)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] active:bg-[var(--surface-selected)]",
  ghost: "bg-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] active:bg-[var(--surface-selected)]",
  success: "bg-[var(--status-success-solid)] text-[var(--text-on-accent)] hover:bg-[var(--status-success-text)] active:bg-[var(--status-success-text)]",
  warning: "bg-[var(--status-warning-bg)] text-[var(--status-warning-text)] hover:bg-[var(--status-warning-border)] active:bg-[var(--status-warning-border)]",
  danger: "bg-[var(--status-danger-solid)] text-[var(--text-on-accent)] hover:bg-[var(--status-danger-text)] active:bg-[var(--status-danger-text)]",
  contextual: "bg-[var(--status-info-bg)] text-[var(--status-info-text)] hover:bg-[var(--status-info-border)] active:bg-[var(--status-info-border)]",
};

const sizeClasses: Record<ChatButtonSize, string> = {
  m: "h-8 gap-1.5 rounded-[var(--radius-md)] px-3 text-xs",
  l: "h-9 gap-2 rounded-[var(--radius-md)] px-3.5 text-sm",
};

interface ChatButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: ChatButtonTone;
  size?: ChatButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
  iconAfter?: React.ReactNode;
}

/** The semantic action language used only inside the conversation workspace. */
export const ChatButton = forwardRef<HTMLButtonElement, ChatButtonProps>(function ChatButton(
  {
    children,
    className,
    disabled,
    icon,
    iconAfter,
    loading = false,
    size = "m",
    tone = "secondary",
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium leading-none",
        "transition-[background-color,color,box-shadow,opacity] duration-[var(--duration-base)] ease-[var(--ease-out)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface-canvas)]",
        "disabled:pointer-events-none disabled:opacity-45",
        toneClasses[tone],
        sizeClasses[size],
        className,
      )}
      disabled={disabled || loading}
      type={type}
    >
      {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : icon}
      {children}
      {!loading && iconAfter}
    </button>
  );
});

interface ChatIconButtonProps extends Omit<ChatButtonProps, "children" | "icon"> {
  "aria-label": string;
  icon: React.ReactNode;
}

/** An accessible, square control for the monochrome Lucide system icon set. */
export const ChatIconButton = forwardRef<HTMLButtonElement, ChatIconButtonProps>(function ChatIconButton(
  { className, icon, size = "m", ...props },
  ref,
) {
  const dimension = size === "l" ? "h-9 w-9" : "h-8 w-8";
  return (
    <ChatButton
      {...props}
      ref={ref}
      className={cn(dimension, "px-0", className)}
      size={size}
    >
      {icon}
    </ChatButton>
  );
});
