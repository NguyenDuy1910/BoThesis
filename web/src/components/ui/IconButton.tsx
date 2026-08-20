"use client";

import { cn } from "@/lib/cn";
import { Loader2 } from "lucide-react";

type IconButtonVariant = "ghost" | "secondary" | "danger" | "primary";
type IconButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<IconButtonVariant, string> = {
  ghost: "border border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-950",
  secondary:
    "border border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950",
  danger: "border border-transparent text-slate-500 hover:bg-red-50 hover:text-red-700",
  primary: "border border-teal-700 bg-teal-700 text-white hover:bg-teal-800",
};

const sizeClasses: Record<IconButtonSize, string> = {
  sm: "h-7 w-7 rounded-md",
  md: "h-8 w-8 rounded-md",
  lg: "h-9 w-9 rounded-md",
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
      aria-label={label}
      title={props.title ?? label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/25 focus-visible:ring-offset-1 focus-visible:ring-offset-white",
        "disabled:pointer-events-none disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-300 disabled:shadow-none",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : children}
    </button>
  );
}
