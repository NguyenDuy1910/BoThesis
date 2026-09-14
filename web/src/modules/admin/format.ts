import { describeRequestFailure } from "@/lib/api/errors";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Absolute timestamp, for tooltips and anywhere precision matters. */
export function formatDateTime(value?: string | null, fallback = "Never") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatDate(value?: string | null, fallback = "Never") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

/**
 * Admins scan lists for what moved recently, so recent rows read as "12m ago"
 * and older ones fall back to a date. The exact value stays in the title
 * attribute wherever this is used.
 */
export function formatRelative(value?: string | null, fallback = "Never") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  const delta = Date.now() - date.getTime();
  if (delta < 0) return formatDateTime(value, fallback);
  if (delta < MINUTE) return "Just now";
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}m ago`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h ago`;
  if (delta < 7 * DAY) return `${Math.floor(delta / DAY)}d ago`;
  return formatDate(value, fallback);
}

export function formatBytes(value?: number | null) {
  if (!value || value < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** exponent).toFixed(exponent ? 1 : 0)} ${units[exponent]}`;
}

export function titleCase(value?: string | null) {
  return String(value ?? "")
    .replaceAll(/[._-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** File extension, used as a short human label for a document. */
export function fileKind(title?: string | null, documentType?: string | null) {
  const extension = title?.match(/\.([a-z0-9]{1,6})$/i)?.[1];
  if (extension) return extension.toUpperCase();
  return titleCase(documentType) || "File";
}

export function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

export function errorMessage(error: unknown, subject = "The request") {
  return describeRequestFailure(error, subject);
}

/**
 * Audit actions arrive as `document.uploaded`. Administrators read sentences,
 * not dotted paths.
 */
export function describeAuditAction(action?: string | null) {
  // The last dotted segment is the verb; everything before it names the thing
  // it happened to, which may itself be several segments
  // (`integration.connection.created` -> "Created integration connection").
  const parts = String(action ?? "").split(".").filter(Boolean);
  if (parts.length < 2) return titleCase(action) || "Unknown action";
  const verb = parts.pop()!.replaceAll("_", " ");
  const resource = parts.join(" ").replaceAll("_", " ");
  return `${verb.charAt(0).toUpperCase()}${verb.slice(1)} ${resource}`;
}
