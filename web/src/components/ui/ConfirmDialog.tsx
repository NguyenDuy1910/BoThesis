"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState } from "@/components/ui/ErrorState";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  title: string;
  /** What will happen, in one or two sentences the user can act on. */
  description: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
}

/**
 * Every irreversible action goes through this, so the wording, the button
 * order and the error handling are the same wherever it is used.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive = true,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "The action could not be completed.",
      );
    } finally {
      setPending(false);
    }
  }

  if (!open) return null;

  return (
    <Dialog
      className="max-w-md"
      footer={
        <>
          <Button
            disabled={pending}
            onClick={() => {
              setError(null);
              onClose();
            }}
            variant="ghost"
          >
            {cancelLabel}
          </Button>
          <Button
            loading={pending}
            onClick={confirm}
            variant={destructive ? "destructive" : "primary"}
          >
            {confirmLabel}
          </Button>
        </>
      }
      onClose={() => {
        if (pending) return;
        setError(null);
        onClose();
      }}
      open
      title={title}
    >
      <div className="space-y-3">
        <div className="text-[length:var(--text-size-ui)] leading-5 text-[var(--text-secondary)]">
          {description}
        </div>
        {error && <ErrorState description={error} layout="inline" />}
      </div>
    </Dialog>
  );
}
