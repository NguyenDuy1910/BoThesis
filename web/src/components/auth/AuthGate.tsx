"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { getApiConfiguration } from "@/lib/api/config";

const publicPathPrefix = "/auth/";

/**
 * Keeps protected application views unmounted until browser-held session state
 * has been checked. API authorization remains enforced by the backend.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authorizedPath, setAuthorizedPath] = useState<string | null>(null);
  const isPublicRoute = pathname.startsWith(publicPathPrefix);
  const hasAccess = isPublicRoute || authorizedPath === pathname;

  useEffect(() => {
    if (isPublicRoute) return;
    if (getApiConfiguration()) {
      setAuthorizedPath(pathname);
      return;
    }
    setAuthorizedPath(null);
    router.replace(`/auth/login?next=${encodeURIComponent(pathname)}`);
  }, [isPublicRoute, pathname, router]);

  if (hasAccess) return <>{children}</>;
  return <div aria-busy="true" aria-label="Checking access" className="auth-gate" role="status" />;
}
