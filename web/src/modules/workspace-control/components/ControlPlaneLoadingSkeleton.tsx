import { Skeleton, TableSkeleton } from "@/components/ui/Skeleton";

export type ControlPlaneLoadingVariant =
  | "overview"
  | "settings"
  | "access"
  | "knowledge"
  | "audit"
  | "integrations"
  | "platform-tenants"
  | "platform-users"
  | "platform-system";

/** Control-plane loading stays shaped like the active section, not a chat page. */
export function ControlPlaneLoadingSkeleton({
  variant = "overview",
}: {
  variant?: ControlPlaneLoadingVariant;
}) {
  return (
    <section
      aria-busy="true"
      aria-label="Loading workspace control"
      className="control-loading"
      role="status"
    >
      <span className="sr-only">Loading workspace control</span>
      {variant === "overview" && <OverviewLoading />}
      {variant === "settings" && <SettingsLoading />}
      {variant === "platform-system" && <SystemLoading />}
      {isTableVariant(variant) && <TablePageLoading variant={variant} />}
    </section>
  );
}

function isTableVariant(
  variant: ControlPlaneLoadingVariant,
): variant is Exclude<ControlPlaneLoadingVariant, "overview" | "settings" | "platform-system"> {
  return variant !== "overview" && variant !== "settings" && variant !== "platform-system";
}

function LoadingHeading() {
  return (
    <div className="control-loading__heading" aria-hidden="true">
      <Skeleton className="h-2.5 w-20" />
      <Skeleton className="h-7 w-56" />
      <Skeleton className="h-3 w-[min(32rem,80%)]" />
    </div>
  );
}

function OverviewLoading() {
  return (
    <>
      <LoadingHeading />
      <div className="control-loading__stats" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <div className="ctl-stat" key={index}>
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-7 w-14" />
            <Skeleton className="h-2.5 w-24" />
          </div>
        ))}
      </div>
      <div className="control-loading__columns" aria-hidden="true">
        {[0, 1].map((column) => (
          <div className="ctl-card p-4" key={column}>
            <Skeleton className="h-4 w-32" />
            {Array.from({ length: 4 }).map((_, index) => (
              <div className="control-loading__line" key={index}>
                <Skeleton className="h-3 w-[62%]" />
                <Skeleton className="h-3 w-10" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

function SettingsLoading() {
  return (
    <>
      <LoadingHeading />
      <div className="ctl-card control-loading__form" aria-hidden="true">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="mt-5 h-3 w-16" />
        <Skeleton className="mt-2 h-10 w-full" />
        <Skeleton className="mt-5 h-3 w-16" />
        <Skeleton className="mt-2 h-10 w-full" />
        <Skeleton className="mt-5 h-3 w-20" />
        <Skeleton className="mt-2 h-5 w-20" />
      </div>
    </>
  );
}

function SystemLoading() {
  return (
    <>
      <div className="control-loading__stats" aria-hidden="true">
        {Array.from({ length: 3 }).map((_, index) => (
          <div className="ctl-stat" key={index}>
            <Skeleton className="h-2.5 w-24" />
            <Skeleton className="h-7 w-24" />
            <Skeleton className="h-2.5 w-28" />
          </div>
        ))}
      </div>
      <div className="ctl-card control-loading__table" aria-hidden="true">
        <Skeleton className="h-4 w-36" />
        <TableSkeleton rows={5} columns={2} />
      </div>
    </>
  );
}

function TablePageLoading({ variant }: { variant: Exclude<ControlPlaneLoadingVariant, "overview" | "settings" | "platform-system"> }) {
  const columns = variant === "platform-tenants" ? 5 : variant === "integrations" ? 3 : 4;
  const rows = variant === "access" ? 6 : variant === "knowledge" ? 6 : 7;
  return (
    <>
      <LoadingHeading />
      <div className="control-loading__toolbar" aria-hidden="true">
        <Skeleton className="h-9 w-52" />
        <Skeleton className="h-9 w-28" />
        <Skeleton className="ml-auto h-3 w-24" />
      </div>
      <div className="ctl-card control-loading__table" aria-hidden="true">
        <TableSkeleton rows={rows} columns={columns} />
      </div>
    </>
  );
}
