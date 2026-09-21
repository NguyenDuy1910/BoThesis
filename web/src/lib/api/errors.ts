/**
 * Turns a thrown request failure into something an operator can act on.
 *
 * A browser surfaces a dropped connection as the string "Failed to fetch",
 * and an expired session as a bare 401. Neither tells the reader what went
 * wrong or what to do, so both are translated here — once, for every surface —
 * into a cause and a next step. Messages the API itself wrote are already
 * operator-facing and pass through unchanged.
 */
const NETWORK_HINTS = [
  "failed to fetch",
  "networkerror",
  "load failed",
  "network request failed",
  "fetch failed",
];

export function describeRequestFailure(
  error: unknown,
  subject = "This view",
): string {
  const raw = error instanceof Error ? error.message.trim() : String(error ?? "").trim();
  const lower = raw.toLowerCase();

  if (!raw) return `${subject} could not be loaded. Try again in a moment.`;

  if (NETWORK_HINTS.some((hint) => lower.includes(hint))) {
    return `${subject} could not reach the API. Check your connection, then try again.`;
  }
  if (lower.includes("401") || lower.includes("unauthorized")) {
    return "Your session has expired. Sign in again to continue.";
  }
  if (lower.includes("403") || lower.includes("forbidden")) {
    return `Your workspace role does not allow you to view ${subject.toLowerCase()}.`;
  }
  if (lower.includes("404") || lower.includes("not found")) {
    return `${subject} no longer exists, or was moved.`;
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return `${subject} took too long to load. The API may be under load — try again.`;
  }
  return raw;
}
