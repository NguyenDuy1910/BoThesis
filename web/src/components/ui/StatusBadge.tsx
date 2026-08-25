import { Badge } from "@/components/ui/Badge";

const positiveStatuses = new Set([
  "active",
  "approved",
  "available",
  "completed",
  "connected",
  "indexed",
  "ready",
  "success",
]);
const dangerStatuses = new Set(["denied", "error", "failed", "unsupported"]);
const progressStatuses = new Set(["draft", "indexing", "pending", "processing", "running", "syncing"]);
const neutralStatuses = new Set(["cancelled", "deleted", "disabled", "hidden", "inactive", "none", "retired", "skipped"]);

export function StatusBadge({ status }: { status: string }) {
  const normalized = status?.toLowerCase() || "unknown";
  const variant = positiveStatuses.has(normalized)
    ? "success"
    : dangerStatuses.has(normalized)
      ? "danger"
      : progressStatuses.has(normalized)
        ? "info"
        : neutralStatuses.has(normalized)
          ? "default"
          : "warning";
  return <Badge dot variant={variant}>{statusLabel(normalized)}</Badge>;
}

function statusLabel(value: string) {
  return value
    .replaceAll(/[._-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
