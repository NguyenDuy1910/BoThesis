import { Skeleton } from "@/components/ui/Skeleton";

/** Session bootstrap is route-neutral, so keep it compact and content-agnostic. */
export function AuthLoadingSkeleton() {
  return (
    <main aria-busy="true" aria-label="Checking session" className="session-loading" role="status">
      <span className="sr-only">Checking session</span>
      <div className="session-loading__card" aria-hidden="true">
        <Skeleton className="h-10 w-10 rounded-[var(--radius-md)]" />
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-2.5 w-48 max-w-full" />
        </div>
      </div>
    </main>
  );
}
