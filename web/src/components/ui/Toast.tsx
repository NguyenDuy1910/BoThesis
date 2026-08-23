"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { cn } from "@/lib/cn";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";

type ToastVariant = "success" | "error" | "info";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toast: (opts: { title: string; description?: string; variant?: ToastVariant; duration?: number }) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

const VARIANT_STYLES: Record<ToastVariant, { icon: React.ReactNode; border: string }> = {
  success: { icon: <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-[var(--success)]" />, border: "border-l-[var(--success)]" },
  error: { icon: <XCircle aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />, border: "border-l-[var(--danger)]" },
  info: { icon: <Info aria-hidden="true" className="h-4 w-4 text-[var(--brand-accent)]" />, border: "border-l-[var(--brand-accent)]" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback(
    ({ title, description, variant = "info", duration = 4000 }: { title: string; description?: string; variant?: ToastVariant; duration?: number }) => {
      const id = Math.random().toString(36).slice(2);
      setToasts((prev) => [...prev, { id, title, description, variant }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, duration);
    },
    []
  );

  const dismiss = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-label="Notifications"
        className="fixed bottom-4 right-4 z-[100] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((t) => {
          const style = VARIANT_STYLES[t.variant];
          return (
            <div
              key={t.id}
              role={t.variant === "error" ? "alert" : "status"}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-l-4 border-[var(--border)] bg-[var(--surface)] p-3 text-[var(--text)] shadow-[var(--shadow-lg)]",
                "animate-in slide-in-from-right-full fade-in-0 duration-200",
                style.border
              )}
            >
              <div className="mt-0.5 shrink-0">{style.icon}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[var(--text)]">{t.title}</p>
                {t.description && (
                  <p className="mt-0.5 text-sm leading-5 text-[var(--text-muted)]">{t.description}</p>
                )}
              </div>
              <button
                aria-label={`Dismiss ${t.title} notification`}
                onClick={() => dismiss(t.id)}
                className="shrink-0 rounded p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                type="button"
              >
                <X aria-hidden="true" className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
