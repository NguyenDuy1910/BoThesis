"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AuthPromptProvider } from "@/components/auth/AuthPrompt";
import { getStoredAuthSession, isGuestSession } from "@/lib/auth/session";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { createSession } from "@/modules/auth/api";

const publicPathPrefix = "/auth/";

/**
 * Keeps protected application views unmounted until browser-held session state
 * has been checked. API authorization remains enforced by the backend.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useAuthSession();
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requiredPrompt, setRequiredPrompt] = useState<{
    reason: string;
    requestId: number;
  }>();
  const isPublicRoute = pathname.startsWith(publicPathPrefix);

  useEffect(() => {
    if (isPublicRoute) return;
    if (getStoredAuthSession()) {
      setChecking(false);
      return;
    }
    let mounted = true;
    setChecking(true);
    setError(null);
    void createSession()
      .catch((cause: unknown) => {
        if (mounted) {
          setError(cause instanceof Error ? cause.message : "Guest access could not be started.");
        }
      })
      .finally(() => { if (mounted) setChecking(false); });
    return () => { mounted = false; };
  }, [isPublicRoute]);

  useEffect(() => {
    if (!isGuestSession(session)) {
      setRequiredPrompt(undefined);
      return;
    }
    const reason = protectedRouteReason(pathname);
    if (!reason) return;
    setRequiredPrompt((current) => ({
      reason,
      requestId: (current?.requestId ?? 0) + 1,
    }));
    router.replace("/app");
  }, [pathname, router, session]);

  if (isPublicRoute) return <>{children}</>;
  if (!checking && session) {
    return (
      <AuthPromptProvider
        requiredReason={requiredPrompt?.reason}
        requiredRequestId={requiredPrompt?.requestId}
      >
        {children}
      </AuthPromptProvider>
    );
  }
  return (
    <div aria-busy="true" className="auth-gate" role="status">
      <span aria-hidden="true" className="shell__route-boundary-indicator" />
      <span>{error ?? "Opening public workspace…"}</span>
      {error && <button onClick={() => window.location.reload()} type="button">Try again</button>}
    </div>
  );
}

function protectedRouteReason(pathname: string): string | undefined {
  if (pathname === "/library") return "Sign in to upload and keep private files.";
  if (pathname === "/workspaces") return "Sign in to open private workspaces.";
  if (pathname === "/workspace-control" || pathname.startsWith("/workspace-control/")) {
    return "Sign in to manage agents, knowledge, and workspace settings.";
  }
  return undefined;
}
