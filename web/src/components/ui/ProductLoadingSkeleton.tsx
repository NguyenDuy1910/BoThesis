import { Skeleton } from "@/components/ui/Skeleton";

/** Neutral fallback for product routes without a page-specific boundary. */
export function ProductLoadingSkeleton() {
  return (
    <section aria-busy="true" aria-label="Loading page" className="product-loading" role="status">
      <span className="sr-only">Loading page</span>
      <div className="product-loading__inner" aria-hidden="true">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-3 w-[min(32rem,80%)]" />
        <div className="product-loading__body">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-[82%]" />
        </div>
      </div>
    </section>
  );
}
