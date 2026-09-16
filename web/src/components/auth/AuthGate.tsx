"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { getApiConfiguration } from "@/lib/api/config";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

const publicPathPrefix = "/auth/";

/**
 * Keeps protected application views unmounted until browser-held session state
 * has been checked. API authorization remains enforced by the backend.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useAuthSession();
  const [isAuthorized, setIsAuthorized] = useState(false);
  const isPublicRoute = pathname.startsWith(publicPathPrefix);

  useEffect(() => {
    if (isPublicRoute) return;
    if (getApiConfiguration()) {
      setIsAuthorized(true);
      return;
    }
    setIsAuthorized(false);
    router.replace(`/auth/login?next=${encodeURIComponent(pathname)}`);
  }, [isPublicRoute, pathname, router, session]);

  if (isPublicRoute || isAuthorized) return <>{children}</>;
  return (
    <div aria-busy="true" className="auth-gate" role="status">
      <span aria-hidden="true" className="shell__route-boundary-indicator" />
      <span>Checking workspace access…</span>
    </div>
  );
}
