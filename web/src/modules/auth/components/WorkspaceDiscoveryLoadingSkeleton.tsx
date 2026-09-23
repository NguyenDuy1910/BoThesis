import { Skeleton } from "@/components/ui/Skeleton";

/** Workspace directory loading mirrors searchable workspace rows. */
export function WorkspaceDiscoveryLoadingSkeleton() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading workspaces"
      className="mx-auto w-full max-w-6xl p-[var(--page-gutter)] workspace-discovery-loading"
      role="status"
    >
      <span className="sr-only">Loading workspaces</span>
      <Skeleton className="mb-5 h-7 w-48" />
      <div className="utility-bar workspace-discovery-loading__toolbar" aria-hidden="true">
        <Skeleton className="h-9 min-w-56 flex-1" />
        <Skeleton className="h-3 w-24" />
      </div>
      <div className="workspace-discovery-loading__rows" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <div className="workspace-discovery-loading__row" key={index}>
            <Skeleton className="h-10 w-10 rounded-full" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-3 w-[44%]" />
              <Skeleton className="h-2.5 w-[28%]" />
              <Skeleton className="h-2.5 w-[36%]" />
            </div>
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </div>
    </section>
  );
}
