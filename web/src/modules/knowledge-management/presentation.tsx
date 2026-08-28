export { StatusBadge } from "@/components/ui/StatusBadge";

export function titleCase(value: string) {
  return String(value ?? "")
    .replaceAll(/[._-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatDate(value?: string | null) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatBytes(value?: number | null) {
  if (!value) return "Size unknown";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** exponent).toFixed(exponent ? 1 : 0)} ${units[exponent]}`;
}

export function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "The knowledge management request could not be completed.";
}
