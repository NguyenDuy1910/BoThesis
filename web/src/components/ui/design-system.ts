export const ui = {
  page: "w-full space-y-4",
  pageNarrow: "mx-auto w-full max-w-5xl space-y-4",
  pageWide: "w-full space-y-4",
  sectionTitle: "text-sm font-semibold text-[var(--text)]",
  sectionDescription: "mt-1 text-sm leading-5 text-[var(--text-muted)]",
  label: "text-sm font-medium text-[var(--text-secondary)]",
  helper: "text-sm leading-5 text-[var(--text-muted)]",
  metaLabel: "text-xs font-medium text-[var(--text-muted)]",
  metaValue: "text-sm font-medium text-[var(--text)]",
  focus:
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--surface)]",
  control:
    "h-10 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--text)] transition-[border-color,box-shadow,background-color] placeholder:text-[var(--text-muted)] hover:border-[var(--border-strong)] focus:border-[var(--brand-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:bg-[var(--bg-subtle)] disabled:text-[var(--text-muted)]",
  textarea:
    "min-h-20 w-full resize-y rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm leading-5 text-[var(--text)] transition-[border-color,box-shadow,background-color] placeholder:text-[var(--text-muted)] hover:border-[var(--border-strong)] focus:border-[var(--brand-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:bg-[var(--bg-subtle)] disabled:text-[var(--text-muted)]",
  panel:
    "rounded-lg border border-[var(--border)] bg-[var(--surface)]",
  insetPanel:
    "rounded-md border border-[var(--border)] bg-[var(--bg-panel)]",
  subtlePanel:
    "rounded-md border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2",
  toggle:
    "flex min-h-10 w-full items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-left text-sm text-[var(--text-secondary)] transition-[border-color,background-color] hover:border-[var(--border-strong)] hover:bg-[var(--bg-panel)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
  switchTrack: "relative h-5 w-9 shrink-0 rounded-full transition-colors",
  switchThumb:
    "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
  iconButton:
    "inline-flex shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] transition-[background-color,color] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] active:bg-[var(--surface-selected)] disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
  dangerFocus:
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/20 focus-visible:ring-offset-1 focus-visible:ring-offset-white",
  toolbar:
    "flex min-h-11 flex-wrap items-center gap-2 border-y border-[var(--border)] bg-[var(--surface)] px-3 py-2",
  tableShell:
    "overflow-x-auto border-y border-[var(--border)] bg-[var(--surface)]",
  adminSection:
    "border-y border-[var(--border)] bg-[var(--surface)]",
};
