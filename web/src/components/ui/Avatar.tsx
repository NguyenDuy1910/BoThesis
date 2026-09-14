"use client";

import { cn } from "@/lib/cn";

const sizeClasses = {
  xs: "h-5 w-5 text-[0.5625rem]",
  sm: "h-6 w-6 text-[0.625rem]",
  md: "h-7 w-7 text-[length:var(--text-size-caption)]",
  rail: "h-[26px] w-[26px] text-[0.625rem]",
  lg: "h-9 w-9 text-xs",
} as const;

/**
 * Deterministic hue so the same person keeps the same colour on every screen,
 * confined to a band around the brand violet.
 *
 * A full 360° spread puts some avatars in green, amber and red — the three
 * hues that mean something specific in this console. A person is not a status,
 * so the band stops short of them while still separating one face from the
 * next. Saturation and lightness are fixed at values that clear 4.5:1 against
 * the white initials across the whole band.
 */
const HUE_START = 225;
const HUE_RANGE = 60;

function hueFor(seed: string) {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) % 360;
  }
  return HUE_START + (hash % HUE_RANGE);
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
