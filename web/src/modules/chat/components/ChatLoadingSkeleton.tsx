import { Skeleton } from "@/components/ui/Skeleton";

/** Chat loading mirrors conversation transcript and composer geometry. */
export function ChatLoadingSkeleton() {
  return (
    <section
      aria-busy="true"
      aria-label="Loading chat"
      className="chat-loading"
      role="status"
    >
      <span className="sr-only">Loading chat</span>
      <div className="chat-loading__inner">
        <header className="chat-loading__topbar" aria-hidden="true">
          <Skeleton className="h-2 w-16" />
          <Skeleton className="h-3 w-32" />
        </header>
        <div className="chat-loading__transcript" aria-hidden="true">
          <div className="chat-loading__user">
            <Skeleton className="h-3 w-[min(52%,28rem)]" />
            <Skeleton className="h-3 w-[min(30%,16rem)]" />
          </div>
          <div className="chat-loading__assistant">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-[62%]" />
          </div>
        </div>
        <div className="chat-loading__composer" aria-hidden="true">
          <Skeleton className="h-4 w-[68%]" />
          <div className="chat-loading__composer-footer">
            <Skeleton className="h-8 w-[4.5rem] rounded-[var(--radius-md)]" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="ml-auto h-8 w-8 rounded-full" />
          </div>
        </div>
      </div>
    </section>
  );
}
