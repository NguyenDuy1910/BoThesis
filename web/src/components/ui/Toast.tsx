"use client";

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";

import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";

type ToastVariant = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  action?: { label: string; onClick: () => void };
}

interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
  /** One follow-up, e.g. "View collection" after a create. */
  action?: { label: string; onClick: () => void };
}

const ToastContext = createContext<{ toast: (options: ToastOptions) => void } | null>(
  null,
);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}

const variantIcon: Record<ToastVariant, React.ReactNode> = {
  success: (
    <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[var(--status-success-solid)]" />
  ),
  error: <XCircle aria-hidden="true" className="h-4 w-4 text-[var(--status-danger-solid)]" />,
  warning: (
    <AlertTriangle aria-hidden="true" className="h-4 w-4 text-[var(--status-warning-solid)]" />
  ),
  info: <Info aria-hidden="true" className="h-4 w-4 text-[var(--status-info-solid)]" />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const toast = useCallback(
    ({ title, description, variant = "info", duration, action }: ToastOptions) => {
      const id = Math.random().toString(36).slice(2);
      setToasts((current) => [...current, { id, title, description, variant, action }]);
      // Failures stay until dismissed: an admin who missed the toast has no
      // other way to find out what went wrong.
      const life = duration ?? (variant === "error" ? 10_000 : 4500);
      setTimeout(() => dismiss(id), life);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-label="Notifications"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((entry) => (
          <div
            className={cn(
              "pointer-events-auto flex items-start gap-2.5 rounded-[var(--radius-md)] bg-[var(--surface-raised)] p-3",
              "shadow-[var(--elevation-3)] motion-safe:animate-[ctl-pop_var(--duration-base)_var(--ease-out)_both]",
            )}
            key={entry.id}
            role={entry.variant === "error" ? "alert" : "status"}
          >
            <span className="mt-px shrink-0">{variantIcon[entry.variant]}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[length:var(--text-size-ui)] font-semibold text-[var(--text-primary)]">
                {entry.title}
              </p>
              {entry.description && (
                <p className="mt-0.5 text-[length:var(--text-size-meta)] leading-4 text-[var(--text-tertiary)]">
                  {entry.description}
                </p>
              )}
              {entry.action && (
                <button
                  className="mt-1.5 text-[length:var(--text-size-meta)] font-semibold text-[var(--text-accent)] underline-offset-4 hover:underline"
                  onClick={() => {
                    entry.action?.onClick();
                    dismiss(entry.id);
                  }}
                  type="button"
                >
                  {entry.action.label}
                </button>
              )}
            </div>
            <button
              aria-label={`Dismiss ${entry.title}`}
              className={cn(ui.iconButton, "h-6 w-6 shrink-0")}
              onClick={() => dismiss(entry.id)}
              type="button"
            >
              <X aria-hidden="true" className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
