"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AuthPromptProvider } from "@/components/auth/AuthPrompt";
import { AuthLoadingSkeleton } from "@/components/auth/AuthLoadingSkeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { getStoredAuthSession, isGuestSession } from "@/lib/auth/session";
import { useAuthSession } from "@/lib/hooks/useAuthSession";
import { createSession } from "@/modules/auth/api";
import { ChatLoadingSkeleton } from "@/modules/chat/components/ChatLoadingSkeleton";
import { WorkspaceDiscoveryLoadingSkeleton } from "@/modules/auth/components/WorkspaceDiscoveryLoadingSkeleton";
import { LibraryLoadingSkeleton } from "@/modules/library/LibraryLoadingSkeleton";
import { ControlPlaneLoadingSkeleton, type ControlPlaneLoadingVariant } from "@/modules/workspace-control/components/ControlPlaneLoadingSkeleton";

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
  const [retryCount, setRetryCount] = useState(0);
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
  }, [isPublicRoute, retryCount]);

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
  if (error) {
    return (
      <ErrorState
        actionLabel="Try again"
        description={error}
        onAction={() => {
          setError(null);
          setRetryCount((value) => value + 1);
        }}
        title="Workspace could not be opened"
      />
    );
  }
  return <RouteLoading pathname={pathname} />;
}

function RouteLoading({ pathname }: { pathname: string }) {
  if (pathname === "/app") return <ChatLoadingSkeleton />;
  if (pathname === "/library") return <LibraryLoadingSkeleton />;
  if (pathname === "/workspaces") return <WorkspaceDiscoveryLoadingSkeleton />;
  if (pathname === "/workspace-control" || pathname.startsWith("/workspace-control/")) {
    const variant = controlLoadingVariant(pathname);
    return variant ? <ControlPlaneLoadingSkeleton variant={variant} /> : <AuthLoadingSkeleton />;
  }
  return <AuthLoadingSkeleton />;
}

function controlLoadingVariant(pathname: string): ControlPlaneLoadingVariant | undefined {
  const sections = pathname.replace(/^\/workspace-control\/?/, "").split("/");
  const section = sections[0];
  if (!section) return "overview";
  if (section === "settings") return "settings";
  if (section === "access") return "access";
  if (section === "activity") return "audit";
  if (section === "knowledge") return "knowledge";
  if (section !== "platform") return undefined;

  switch (sections[1] ?? "tenants") {
    case "tenants":
      return "platform-tenants";
    case "users":
      return "platform-users";
    case "integrations":
      return "integrations";
    case "audit":
      return "audit";
    case "system":
      return "platform-system";
    default:
      return undefined;
  }
}

function protectedRouteReason(pathname: string): string | undefined {
  if (pathname === "/library") return "Sign in to upload and keep private files.";
  if (pathname === "/workspaces") return "Sign in to open private workspaces.";
  if (pathname === "/workspace-control" || pathname.startsWith("/workspace-control/")) {
    return "Sign in to manage agents, knowledge, and workspace settings.";
  }
  return undefined;
}
