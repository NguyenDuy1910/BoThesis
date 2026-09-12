/**
 * Class recipes shared by every control in the console.
 *
 * Colour, shape, spacing and motion all resolve to the tokens declared in
 * `src/app/admin.css`; nothing here hard-codes a value. A component that needs
 * a different look changes a token, not a class string in one file.
 */

const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface-canvas)]";

const fieldBase = [
  "w-full bg-[var(--surface-base)] text-[0.8125rem] text-[var(--text-primary)]",
  "shadow-[inset_0_0_0_1px_var(--border-default)]",
  "transition-[box-shadow,background-color] duration-[var(--duration-fast)] ease-[var(--ease-out)]",
  "placeholder:text-[var(--text-tertiary)]",
  "hover:shadow-[inset_0_0_0_1px_var(--border-default)]",
  "focus:outline-none focus-visible:outline-none",
  "focus:shadow-[inset_0_0_0_1px_var(--text-accent),0_0_0_3px_var(--focus-ring-soft)]",
  "disabled:cursor-not-allowed disabled:bg-[var(--surface-inset)] disabled:text-[var(--text-tertiary)] disabled:opacity-60",
  "aria-[invalid=true]:shadow-[inset_0_0_0_1px_var(--status-danger-border)]",
].join(" ");

export const ui = {
  focus: focusRing,

  /** Single-line control: input, select, search. */
  control: `h-9 rounded-[var(--radius-sm)] px-2.5 ${fieldBase}`,

  /** Multi-line control. */
  textarea: `min-h-20 resize-y rounded-[var(--radius-sm)] px-2.5 py-2 leading-5 ${fieldBase}`,

  label: "text-[0.8125rem] font-medium text-[var(--text-secondary)]",
  helper: "text-[0.75rem] leading-4 text-[var(--text-tertiary)]",
  errorText: "text-[0.75rem] leading-4 text-[var(--status-danger-text)]",

  sectionTitle: "text-[0.875rem] font-semibold text-[var(--text-primary)]",
  sectionDescription: "mt-1 text-[0.8125rem] leading-5 text-[var(--text-tertiary)]",

  metaLabel: "text-[0.6875rem] font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]",
  metaValue: "text-[0.8125rem] text-[var(--text-primary)]",

  panel: "adm-card",
  insetPanel:
    "rounded-[var(--radius-md)] bg-[var(--surface-inset)] shadow-[inset_0_0_0_1px_var(--border-subtle)]",

  iconButton: `inline-flex shrink-0 items-center justify-center rounded-[var(--radius-sm)] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)] disabled:pointer-events-none disabled:opacity-45 ${focusRing}`,

  switchTrack: "relative h-5 w-9 shrink-0 rounded-full transition-colors",
  switchThumb: "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",

  toggle: `flex min-h-9 w-full items-center justify-between gap-3 rounded-[var(--radius-sm)] bg-[var(--surface-base)] px-2.5 py-1.5 text-left text-[0.8125rem] text-[var(--text-secondary)] shadow-[inset_0_0_0_1px_var(--border-default)] transition-colors hover:bg-[var(--surface-inset)] ${focusRing}`,

  /** Legacy aliases retained for surfaces outside the Admin console. */
  page: "w-full space-y-4",
  pageNarrow: "mx-auto w-full max-w-5xl space-y-4",
  pageWide: "w-full space-y-4",
  dangerFocus: focusRing,
  subtlePanel:
    "rounded-[var(--radius-sm)] bg-[var(--surface-inset)] px-3 py-2 shadow-[inset_0_0_0_1px_var(--border-subtle)]",
  toolbar: "adm-toolbar",
  tableShell: "adm-table-wrap",
  adminSection: "adm-card",
};
