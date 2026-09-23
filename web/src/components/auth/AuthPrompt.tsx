"use client";

import { KeyRound } from "lucide-react";
import { createContext, use, useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { completeGoogleSignIn, completePasswordSignIn } from "@/modules/auth/api";
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
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const googleButtonHost = useRef<HTMLDivElement>(null);
  const identifierRef = useRef<HTMLInputElement>(null);
  const open = reason !== null;
  const googleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim();
  const googleAvailable = Boolean(googleClientId);

  useEffect(() => {
    if (requiredReason) setReason(requiredReason);
  }, [requiredReason, requiredRequestId]);

  const requestSignIn = useCallback((nextReason = "Sign in to continue.") => {
    setError(null);
    setIdentifier("");
    setPassword("");
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
    const host = googleButtonHost.current;
    if (!googleClientId || !host) return;
    let mounted = true;
    void renderGoogleSignInButton(
      host,
      googleClientId,
      (credential) => { if (mounted) void finishSignIn(credential); },
      (message) => { if (mounted) setError(message); },
    ).catch((cause: unknown) => {
      if (mounted) {
        setError(cause instanceof Error ? cause.message : "Google sign-in could not be loaded.");
      }
    });
    return () => { mounted = false; };
  }, [finishSignIn, googleClientId, open]);

  const submitPassword = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSigningIn(true);
    setError(null);
    try {
      await completePasswordSignIn(identifier, password);
      setReason(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in could not be completed.");
    } finally {
      setIsSigningIn(false);
    }
  }, [identifier, password]);

  return (
    <AuthPromptContext value={{ requestSignIn }}>
      {children}
      <Dialog
        className="max-w-[26rem]"
        initialFocusRef={identifierRef}
        onClose={() => setReason(null)}
        open={open}
        title="Sign in to continue"
      >
        <div className="auth-prompt__body">
          <div>
            <p className="auth-prompt__reason">{reason}</p>
            <p className="auth-prompt__copy">Your conversation stays right where you left it.</p>
          </div>
          <form className="auth-prompt__form" onSubmit={submitPassword}>
            <label className="auth-prompt__field">
              <span>Username or email</span>
              <Input autoCapitalize="none" autoComplete="username" ref={identifierRef} onChange={(event) => setIdentifier(event.target.value)} required value={identifier} />
            </label>
            <label className="auth-prompt__field">
              <span>Password</span>
              <Input autoComplete="current-password" minLength={8} onChange={(event) => setPassword(event.target.value)} required type="password" value={password} />
            </label>
            <button className="auth-prompt__submit" disabled={isSigningIn} type="submit">
              <KeyRound aria-hidden="true" size={16} />
              <span>{isSigningIn ? "Signing in…" : "Sign in"}</span>
            </button>
          </form>
          {googleAvailable && <>
            <div aria-hidden="true" className="auth-prompt__divider"><span>or</span></div>
            <div
              aria-busy={isSigningIn || undefined}
              aria-label="Continue with Google Workspace"
              className="auth-prompt__google"
              ref={googleButtonHost}
            />
          </>}
          {error && <p className="text-sm text-[var(--status-danger-text)]" role="alert">{error}</p>}
          <p className="auth-prompt__hint">Workspace access applies after sign-in.</p>
        </div>
      </Dialog>
    </AuthPromptContext>
  );
}
