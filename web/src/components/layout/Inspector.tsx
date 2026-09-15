"use client";

import { ChevronRight, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Avatar } from "@/components/ui/Avatar";
import { useModalLayer } from "@/lib/hooks/useModalLayer";
import { cn } from "@/lib/cn";

/**
 * The contextual inspector: what the selected object is, what state it is in,
 * why, what access applies and where it came from, and what can be done next.
 *
 * It is a set of pieces rather than one configurable component, because the
 * questions differ by object — a member's access provenance is not a
 * workspace's lifecycle. Feature code composes `MemberInspector`,
 * `WorkspaceInspector` and so on from these.
 *
 * Above `--bp-inspector` it sits beside the collection as a column. Below, it
 * becomes a modal drawer with a full focus trap, because at that width it
 * covers the collection it describes.
 */

interface InspectorProps {
  open: boolean;
  onClose: () => void;
  /** Names the panel for assistive technology, e.g. "Member details". */
  ariaLabel: string;
  children: React.ReactNode;
}

export function Inspector({ open, onClose, ariaLabel, children }: InspectorProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [overlay, setOverlay] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 1279.98px)");
    const sync = () => setOverlay(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useModalLayer({ onClose, open: open && overlay, panelRef });

  if (!open) return null;

  const panel = (
    <aside
      ref={panelRef}
      aria-label={ariaLabel}
      aria-modal={overlay || undefined}
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)]",
        "border border-[var(--border-subtle)] bg-[var(--surface-base)]",
        overlay
          ? "relative z-10 h-full w-full max-w-[26rem] rounded-none border-y-0 border-r-0 shadow-[var(--elevation-3)]"
          : "sticky top-0 max-h-[calc(100dvh-var(--header-h)-var(--space-10))] w-[var(--inspector-w)] shrink-0",
      )}
      role={overlay ? "dialog" : "complementary"}
    >
      {children}
    </aside>
  );

  if (!overlay) return panel;

  return createPortal(
    <div className="fixed inset-0 z-[var(--z-popover)] flex justify-end" role="presentation">
      <button
        aria-label="Close details"
        className="absolute inset-0 cursor-default bg-[var(--overlay-scrim)]"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      {panel}
    </div>,
    document.body,
  );
}

export function InspectorHeader({
  title,
  subtitle,
  avatarName,
  badge,
  actions,
  onClose,
}: {
  title: string;
  subtitle?: string;
  /** Renders an identity avatar; omit for objects that are not people. */
  avatarName?: string;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <header className="flex shrink-0 items-start gap-3 px-4 pb-3 pt-4">
      {avatarName && <Avatar name={avatarName} size="lg" />}
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-[length:var(--text-size-h3)] font-semibold leading-[var(--text-lh-h3)] text-[var(--text-primary)]">
          {title}
        </h2>
        {subtitle && (
          <p className="truncate text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {badge}
        {actions}
        <button
          aria-label="Close details"
          className="inline-flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
          onClick={onClose}
          type="button"
        >
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

/**
 * The trust strip: the few facts that qualify everything below it. Keep it to
 * facts a person would otherwise have to open a section to learn.
 */
export function InspectorMeta({
  items,
  status,
}: {
  items: string[];
  status?: React.ReactNode;
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5 border-y border-[var(--border-subtle)] px-4 py-2.5">
      {items.map((item, index) => (
        <span
          className="flex items-center gap-2 text-[length:var(--text-size-meta)] text-[var(--text-secondary)]"
          key={item}
        >
          {index > 0 && (
            <span aria-hidden="true" className="text-[var(--text-tertiary)]">
              ·
            </span>
          )}
          {item}
        </span>
      ))}
      {status && <span className="ml-auto">{status}</span>}
    </div>
  );
}

/**
 * Something about this object needs attention. States the condition and offers
 * the one action that addresses it — never a bare colour.
 */
export function InspectorAlert({
  tone = "warning",
  title,
  detail,
  action,
}: {
  tone?: "warning" | "danger" | "info";
  title: string;
  detail?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div
      className="flex shrink-0 items-start gap-2.5 border-b border-[var(--border-subtle)] px-4 py-2.5"
      style={{ background: `var(--status-${tone}-bg)` }}
    >
      <span
        aria-hidden="true"
        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: `var(--status-${tone}-solid)` }}
      />
      <div className="min-w-0 flex-1">
        <p
          className="text-[length:var(--text-size-ui)] font-medium"
          style={{ color: `var(--status-${tone}-text)` }}
        >
          {title}
        </p>
        {detail && (
          <p className="text-[length:var(--text-size-meta)] text-[var(--text-secondary)]">{detail}</p>
        )}
      </div>
      {action && (
        <button
          className="shrink-0 rounded-[var(--radius-xs)] px-1 text-[length:var(--text-size-ui)] font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
          onClick={action.onClick}
          style={{ color: `var(--status-${tone}-text)` }}
          type="button"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export function InspectorBody({ children }: { children: React.ReactNode }) {
  return <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>;
}

export function InspectorSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section className="px-4 pt-4">
      <h3 className="pb-1 text-[length:var(--text-size-caption)] font-medium uppercase tracking-[var(--text-tracking-caption)] text-[var(--text-tertiary)]">
        {label}
      </h3>
      <div className="divide-y divide-[var(--border-subtle)]">{children}</div>
    </section>
  );
}

interface InspectorRowProps {
  icon: LucideIcon;
  title: string;
  /** What it currently is. */
  subtitle?: string;
  /**
   * Where the value came from — "Direct assignment", "Inherited from Finance
   * group", "Policy controlled". Provenance is the point of this row: a person
   * should never have to guess why an object has the access it has.
   */
  value?: string;
  onClick?: () => void;
}

export function InspectorRow({
  icon: Icon,
  title,
  subtitle,
  value,
  onClick,
}: InspectorRowProps) {
  const content = (
    <>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--surface-subtle)] text-[var(--text-secondary)]">
        <Icon aria-hidden="true" size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[length:var(--text-size-ui)] font-medium text-[var(--text-primary)]">
          {title}
        </span>
        {subtitle && (
          /* Wraps rather than truncates: this line carries the reason a value
             is what it is, and half a reason is worse than none. */
          <span className="block text-[length:var(--text-size-meta)] leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {subtitle}
          </span>
        )}
      </span>
      {value && (
        <span className="shrink-0 self-start pt-0.5 text-[length:var(--text-size-meta)] text-[var(--text-tertiary)]">
          {value}
        </span>
      )}
      {onClick && (
        <ChevronRight
          aria-hidden="true"
          className="shrink-0 self-center text-[var(--text-tertiary)]"
          size={16}
        />
      )}
    </>
  );

  const className =
    "flex w-full items-start gap-2.5 py-2.5 text-left transition-colors";

  if (!onClick) return <div className={className}>{content}</div>;

  return (
    <button
      className={cn(
        className,
        "-mx-1.5 w-[calc(100%+0.75rem)] rounded-[var(--radius-sm)] px-1.5 hover:bg-[var(--surface-hover)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
      )}
      onClick={onClick}
      type="button"
    >
      {content}
    </button>
  );
}

/**
 * Actions, with the destructive one held apart.
 *
 * `danger` sits in its own corner rather than in the run of ordinary buttons,
 * so the action that cannot be undone is never adjacent to the one that just
 * opens a log.
 */
export function InspectorFooter({
  children,
  danger,
}: {
  children?: React.ReactNode;
  danger?: React.ReactNode;
}) {
  return (
    <footer className="flex shrink-0 items-center gap-2 border-t border-[var(--border-subtle)] px-4 py-3">
      {children}
      {danger && <span className="ml-auto">{danger}</span>}
    </footer>
  );
}
