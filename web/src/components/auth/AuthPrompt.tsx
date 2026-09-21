"use client";

import { Check, LockKeyhole, MessageSquareText, ShieldCheck } from "lucide-react";
import { createContext, use, useCallback, useEffect, useRef, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { completeGoogleSignIn } from "@/modules/auth/api";
import { renderGoogleSignInButton } from "@/modules/auth/google";

interface AuthPromptContextValue {
  requestSignIn: (reason?: string) => void;
}

const AuthPromptContext = createContext<AuthPromptContextValue | null>(null);

export function useAuthPrompt(): AuthPromptContextValue {
  const value = use(AuthPromptContext);
  if (!value) throw new Error("useAuthPrompt must be used inside AuthPromptProvider.");
  return value;
}

export function AuthPromptProvider({
  children,
  requiredReason,
  requiredRequestId,
}: {
  children: React.ReactNode;
  requiredReason?: string;
  requiredRequestId?: number;
}) {
  const [reason, setReason] = useState<string | null>(requiredReason ?? null);
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const googleButtonHost = useRef<HTMLDivElement>(null);
  const open = reason !== null;

  useEffect(() => {
    if (requiredReason) setReason(requiredReason);
  }, [requiredReason, requiredRequestId]);

  const requestSignIn = useCallback((nextReason = "Sign in to continue.") => {
    setError(null);
    setReason(nextReason);
  }, []);

  const finishSignIn = useCallback(async (credential: string) => {
    setIsSigningIn(true);
    setError(null);
    try {
      await completeGoogleSignIn(credential);
      setReason(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Google sign-in could not be completed.");
    } finally {
      setIsSigningIn(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim();
    const host = googleButtonHost.current;
    if (!clientId) {
      setError("Google sign-in is not configured for this deployment.");
      return;
    }
    if (!host) return;
    let mounted = true;
    void renderGoogleSignInButton(
      host,
      clientId,
      (credential) => { if (mounted) void finishSignIn(credential); },
      (message) => { if (mounted) setError(message); },
    ).catch((cause: unknown) => {
      if (mounted) {
        setError(cause instanceof Error ? cause.message : "Google sign-in could not be loaded.");
      }
    });
    return () => { mounted = false; };
  }, [finishSignIn, open]);

  return (
    <AuthPromptContext value={{ requestSignIn }}>
      {children}
      <Dialog
        className="max-w-[27rem]"
        onClose={() => setReason(null)}
        open={open}
        title="Keep going with your account"
      >
        <div className="grid gap-5">
          <div className="auth-prompt__continuity" aria-hidden="true">
            <span><MessageSquareText size={17} /></span>
            <i />
            <span><LockKeyhole size={17} /></span>
            <i />
            <span><Check size={17} /></span>
          </div>
          <div className="grid gap-2">
            <p className="text-sm font-medium text-[var(--text-primary)]">{reason}</p>
            <p className="text-sm leading-6 text-[var(--text-secondary)]">
              Sign in without leaving this chat. Guest messages and current position stay intact.
            </p>
          </div>
          <div
            aria-busy={isSigningIn || undefined}
            aria-label="Continue with Google Workspace"
            className="auth-prompt__google"
            ref={googleButtonHost}
          />
          {isSigningIn && <p className="text-sm text-[var(--text-secondary)]" role="status">Connecting your account…</p>}
          {error && <p className="text-sm text-[var(--status-danger-text)]" role="alert">{error}</p>}
          <div className="flex gap-2.5 rounded-[var(--radius-sm)] bg-[var(--surface-inset)] p-3 text-xs leading-5 text-[var(--text-secondary)]">
            <ShieldCheck aria-hidden="true" className="mt-0.5 shrink-0 text-[var(--text-accent)]" size={17} />
            <span>Workspace permissions apply after sign-in. Public citations remain available in this conversation.</span>
          </div>
        </div>
      </Dialog>
    </AuthPromptContext>
  );
}
