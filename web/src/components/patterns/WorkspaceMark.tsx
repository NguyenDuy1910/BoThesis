import { cn } from "@/lib/cn";

export type WorkspaceMarkTone = "accent" | "neutral" | "soft";
export type WorkspaceMarkSize = "sm" | "md" | "lg";

const TONE: Record<WorkspaceMarkTone, string> = {
  accent: "bg-[var(--accent-primary)] text-[var(--text-on-accent)]",
  neutral: "bg-[var(--status-neutral-solid)] text-[var(--text-on-accent)]",
  soft: "bg-[var(--accent-soft)] text-[var(--text-accent)]",
};

const SIZE: Record<WorkspaceMarkSize, string> = {
  sm: "h-6 w-6 rounded-[var(--radius-sm)] text-[length:var(--text-size-caption)]",
  md: "h-8 w-8 rounded-[var(--radius-md)] text-[length:var(--text-size-ui)]",
  lg: "h-10 w-10 rounded-[var(--radius-lg)] text-[length:var(--text-size-body)]",
};

/**
 * A workspace's identity square: initials, or a logo once one is uploaded.
 *
 * Tone carries a tenant's branding without letting branding touch navigation
 * chrome — the mark changes, the rail around it does not.
 */
export function WorkspaceMark({
  name,
  tone = "accent",
  size = "md",
  className,
}: {
  name: string;
  tone?: WorkspaceMarkTone;
  size?: WorkspaceMarkSize;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium leading-none",
        TONE[tone],
        SIZE[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

/** Two letters: one word gives its first two, several give their first each. */
export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "??";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
