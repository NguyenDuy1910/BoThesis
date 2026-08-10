"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "border border-teal-700 bg-teal-700 text-white hover:border-teal-800 hover:bg-teal-800 active:bg-teal-900",
  secondary:
    "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:bg-slate-100",
  ghost:
    "border border-transparent text-slate-500 hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200",
  danger:
    "border border-red-200 bg-white text-red-700 hover:border-red-300 hover:bg-red-50 active:bg-red-100",
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
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium leading-none transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/25 focus-visible:ring-offset-1 focus-visible:ring-offset-white",
        "disabled:pointer-events-none disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none",
        variantClasses[variant],
        sizeClasses[size],
        selected && variant !== "primary" && "border-teal-200 bg-teal-50 text-teal-800",
        className
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {!loading && icon}
      {children}
    </button>
  );
}
