"use client";

import { cn } from "@/lib/cn";

const sizeClasses = {
  xs: "h-5 w-5 text-[0.5625rem]",
  sm: "h-6 w-6 text-[0.625rem]",
  md: "h-7 w-7 text-[0.6875rem]",
  lg: "h-9 w-9 text-xs",
} as const;

/**
 * Deterministic hue so the same person keeps the same colour on every screen.
 * Saturation and lightness are fixed at values that clear 4.5:1 against the
 * white initials at every hue the hash can produce — the yellows and greens
 * are the binding constraint, so the whole scale sits this dark.
 */
function hueFor(seed: string) {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) % 360;
  }
  return hash;
}

export function initialsOf(name: string) {
  const parts = name
    .replace(/@.*/, "")
    .split(/[\s._-]+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Avatar({
  name,
  size = "md",
  className,
}: {
  name: string;
  size?: keyof typeof sizeClasses;
  className?: string;
}) {
  const hue = hueFor(name || "?");
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        sizeClasses[size],
        className,
      )}
      style={{ background: `hsl(${hue} 46% 32%)` }}
    >
      {initialsOf(name)}
    </span>
  );
}
