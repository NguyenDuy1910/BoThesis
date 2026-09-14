"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** Durable selections share the current route; temporary overlays remain local. */
export function useRouteState(key: string, fallback = "") {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  return [params.get(key) ?? fallback, (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value && value !== fallback) next.set(key, value); else next.delete(key);
    router.replace(pathname + (next.size ? "?" + next.toString() : ""), { scroll: false });
  }] as const;
}
