"use client";

import { SlidersHorizontal } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

/** Platform policy storage is intentionally not inferred from workspace settings. */
export function PlatformPoliciesPage() {
  return (
    <>
      <PageHeader eyebrow="PLATFORM ADMIN" description="Platform defaults are distinct from workspace settings and must show their inheritance explicitly." title="Global policies" />
      <EmptyState description="No durable platform-policy resource is configured yet. Workspace settings are not presented as global defaults, so the inheritance boundary remains explicit." icon={<SlidersHorizontal className="h-5 w-5" />} title="No global policies are configured" />
    </>
  );
}
