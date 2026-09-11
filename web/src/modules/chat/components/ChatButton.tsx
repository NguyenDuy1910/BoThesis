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
  primary: "bg-[var(--chat-action-primary)] text-[var(--chat-action-primary-on)] shadow-[var(--chat-shadow-control)] hover:bg-[var(--chat-action-primary-hover)] active:bg-[var(--chat-action-primary-pressed)]",
  secondary: "bg-[var(--chat-surface-raised)] text-[var(--chat-text-primary)] shadow-[inset_0_0_0_1px_var(--chat-border-strong)] hover:bg-[var(--chat-surface-hover)] active:bg-[var(--chat-surface-selected)]",
  soft: "bg-[var(--chat-action-soft)] text-[var(--chat-text-accent)] hover:bg-[var(--chat-action-soft-hover)] active:bg-[var(--chat-action-soft-pressed)]",
  ghost: "bg-transparent text-[var(--chat-text-secondary)] hover:bg-[var(--chat-surface-hover)] hover:text-[var(--chat-text-primary)] active:bg-[var(--chat-surface-selected)]",
  success: "bg-[var(--chat-action-success)] text-[var(--chat-action-success-on)] hover:bg-[var(--chat-action-success-hover)] active:bg-[var(--chat-action-success-pressed)]",
  warning: "bg-[var(--chat-action-warning)] text-[var(--chat-action-warning-on)] hover:bg-[var(--chat-action-warning-hover)] active:bg-[var(--chat-action-warning-pressed)]",
  danger: "bg-[var(--chat-action-danger)] text-[var(--chat-action-danger-on)] hover:bg-[var(--chat-action-danger-hover)] active:bg-[var(--chat-action-danger-pressed)]",
  contextual: "bg-[var(--chat-action-contextual)] text-[var(--chat-action-contextual-on)] hover:bg-[var(--chat-action-contextual-hover)] active:bg-[var(--chat-action-contextual-pressed)]",
};

const sizeClasses: Record<ChatButtonSize, string> = {
  m: "h-8 gap-1.5 rounded-[var(--chat-radius-control)] px-3 text-xs",
  l: "h-9 gap-2 rounded-[var(--chat-radius-control)] px-3.5 text-sm",
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
        "transition-[background-color,color,box-shadow,opacity] duration-[var(--chat-duration-base)] ease-[var(--chat-ease)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--chat-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--chat-surface-canvas)]",
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
