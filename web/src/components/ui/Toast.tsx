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
  success: { icon: <CheckCircle2 className="h-4 w-4 text-green-500" />, border: "border-l-green-500" },
  error: { icon: <XCircle className="h-4 w-4 text-red-500" />, border: "border-l-red-500" },
  info: { icon: <Info className="h-4 w-4 text-slate-500" />, border: "border-l-slate-400" },
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
      <div className="fixed bottom-4 right-4 z-[100] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => {
          const style = VARIANT_STYLES[t.variant];
          return (
            <div
              key={t.id}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-l-4 border-slate-200 bg-white p-3 shadow-lg shadow-slate-950/10",
                "animate-in slide-in-from-right-full fade-in-0 duration-200",
                style.border
              )}
            >
              <div className="mt-0.5 shrink-0">{style.icon}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-950">{t.title}</p>
                {t.description && (
                  <p className="mt-0.5 text-sm leading-5 text-slate-600">{t.description}</p>
                )}
              </div>
              <button
                onClick={() => dismiss(t.id)}
                className="shrink-0 rounded p-0.5 text-slate-500 hover:text-slate-800"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
