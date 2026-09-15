"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * The rail frame, mounted once per mode.
 *
 * Width, collapse and the mobile overlay live here so no page can move them.
 * Geometry comes from shell.css; this only chooses the surface and the state
 * attributes. Platform Admin sits on a different surface from the two
 * workspace modes, which is one of the signals that it is a separate plane.
 */
export function Rail({
  ariaLabel,
  collapsed,
  mobileOpen,
  onMobileClose,
  surface = "nav",
  onToggleCollapse,
  children,
}: {
  ariaLabel: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onMobileClose: () => void;
  surface?: "nav" | "inset";
  /** Omit to make the rail permanently expanded. */
  onToggleCollapse?: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      {mobileOpen && (
        <button
          aria-label="Close navigation"
          className="fixed inset-0 z-[var(--z-overlay)] bg-[var(--overlay-scrim)] lg:hidden"
          onClick={onMobileClose}
          type="button"
        />
      )}
      <nav
        aria-label={ariaLabel}
        className={cn(
          "shell-nav group/rail relative z-[var(--z-sidebar)] flex shrink-0 flex-col gap-2.5 py-3",
          "border-r border-[var(--border-subtle)]",
          "transition-[width] duration-[var(--duration-base)] ease-[var(--ease-out)]",
          surface === "inset" ? "bg-[var(--surface-inset)]" : "bg-[var(--surface-nav)]",
        )}
        data-collapsed={collapsed || undefined}
        data-open={mobileOpen || undefined}
      >
        {children}
        {onToggleCollapse && <RailEdgeToggle collapsed={collapsed} onToggle={onToggleCollapse} />}
      </nav>
    </>
  );
}

/** A run of rows sharing one inset. Groups are spaced by the rail, not by themselves. */
export function RailGroup({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid grid-cols-[minmax(0,1fr)] gap-0.5 px-3", className)}>{children}</div>;
}

/** A full-width rule between groups. */
export function RailDivider() {
  return <div className="mx-3 h-px shrink-0 bg-[var(--border-subtle)]" role="separator" />;
}

/** Pushes the identity/context dock to the foot of a rail without a scrollable middle. */
export function RailSpacer() {
  return <div className="min-h-0 flex-1" />;
}

/** The uppercase label above a run of rows — or a rule once collapsed. */
export function RailCaption({ children, collapsed }: { children: React.ReactNode; collapsed: boolean }) {
  if (collapsed) return <span className="mx-2 my-1 h-px bg-[var(--border-subtle)]" role="separator" />;
  return (
    <p className="px-2.5 py-0.5 text-[length:var(--text-size-caption)] font-medium uppercase tracking-[var(--text-tracking-caption)] text-[var(--text-tertiary)]">
      {children}
    </p>
  );
}

/**
 * The scrollable middle. Long histories and navigation stay bounded while the
 * contextual header and identity dock remain pinned in the rail frame.
 */
export function RailScroll({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto overflow-x-hidden">{children}</div>
  );
}

/**
 * Collapse, on the rail's trailing edge.
 *
 * The WA rails have no brand row to hang this off, and a permanent button
 * would be chrome competing with navigation. It is invisible at rest and
 * appears on hover or keyboard focus, which keeps the resting rail clean
 * without making the control unreachable.
 */
function RailEdgeToggle({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const Icon = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    <button
      aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
      className={cn(
        "absolute bottom-4 right-0 hidden h-7 w-7 translate-x-1/2 items-center justify-center lg:flex",
        "rounded-full bg-[var(--surface-base)] text-[var(--text-tertiary)]",
        "ring-1 ring-[var(--border-subtle)] shadow-[var(--elevation-1)]",
        "opacity-0 transition-opacity duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        "hover:text-[var(--text-primary)] focus-visible:opacity-100 group-hover/rail:opacity-100",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
      )}
      onClick={onToggle}
      type="button"
    >
      <Icon aria-hidden="true" size={16} />
    </button>
  );
}
