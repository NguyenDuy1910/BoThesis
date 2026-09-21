"use client";

import { AlertTriangle, RotateCcw, SquarePen } from "lucide-react";

import type { TurnRecovery } from "../recovery";
import { ChatButton } from "./ChatButton";

/** A local recovery surface that leaves the surrounding conversation intact. */
export function RecoveryNotice({
  recovery,
  onEditRequest,
  onRetry,
}: {
  recovery: TurnRecovery;
  onEditRequest?: () => void;
  onRetry: () => void;
}) {
  return (
    <section className={`recovery-notice recovery-notice--${recovery.variant}`} role="alert">
      <AlertTriangle aria-hidden="true" className="recovery-notice__icon" size={16} />
      <div className="recovery-notice__body">
        <h3>{recovery.title}</h3>
        <p>{recovery.detail}</p>
        <div className="recovery-notice__actions">
          <ChatButton icon={<RotateCcw aria-hidden="true" size={14} />} onClick={onRetry} tone="primary">
            {recovery.retryLabel}
          </ChatButton>
          {onEditRequest && (
            <ChatButton icon={<SquarePen aria-hidden="true" size={14} />} onClick={onEditRequest} tone="ghost">
              Edit request
            </ChatButton>
          )}
        </div>
      </div>
    </section>
  );
}
