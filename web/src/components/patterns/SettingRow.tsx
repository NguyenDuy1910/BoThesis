import { cn } from "@/lib/cn";

/**
 * Label, consequence, control.
 *
 * Rows are separated by a divider, never by a card each. The consequence line
 * is required — a toggle whose effect is not stated is a support ticket.
 */
export function SettingRow({
  title,
  description,
  note,
  control,
  disabled = false,
}: {
  title: string;
  description: string;
  /** Why this control cannot be operated, when it cannot. */
  note?: React.ReactNode;
  control: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className={cn("flex w-full items-center gap-6 py-3.5", disabled && "opacity-50")}>
      <div className="min-w-0 flex-1">
        <p className="text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
          {title}
        </p>
        <p className="text-[length:var(--text-size-nav)] leading-[var(--text-lh-nav)] text-[var(--text-secondary)]">
          {description}
        </p>
        {note && (
          <p className="mt-1 text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {note}
          </p>
        )}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}
