import { Skeleton } from "@/components/ui/Skeleton";

/** Library loading mirrors its back link, command bar, and document rows. */
export function LibraryLoadingSkeleton() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading library"
      className="document-workspace library-loading"
      role="status"
    >
      <span className="sr-only">Loading your documents</span>
      <div className="library-loading__back px-[var(--page-gutter)] pt-4" aria-hidden="true">
        <Skeleton className="h-8 w-28 rounded-[var(--radius-sm)]" />
      </div>
      <div className="utility-bar library-loading__toolbar" aria-hidden="true">
        <Skeleton className="h-9 min-w-48 flex-1" />
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-9 w-20" />
      </div>
      <div className="library-list px-[var(--page-gutter)] pb-5" aria-hidden="true">
        <Skeleton className="mb-3 mt-4 h-3 w-28" />
        <div className="library-loading__rows">
          {Array.from({ length: 7 }).map((_, index) => (
            <div className="library-loading__row" key={index}>
              <Skeleton className="h-8 w-8 rounded-[var(--radius-xs)]" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-3 w-[62%]" />
                <Skeleton className="h-2.5 w-[34%]" />
              </div>
              <Skeleton className="h-2.5 w-16" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
