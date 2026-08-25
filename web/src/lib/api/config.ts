export interface BothesisChatConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
  dataMode: BothesisDataMode;
}

export type BothesisDataMode = "api" | "mock";

/**
 * Resolve the browser data boundary once instead of scattering environment
 * string checks through features. Mock mode is intentionally explicit: an
 * invalid or missing value keeps production API behaviour.
 */
export function getBothesisDataMode(): BothesisDataMode {
  return process.env.NEXT_PUBLIC_BOTHESIS_DATA_MODE?.trim().toLowerCase() === "mock"
    ? "mock"
    : "api";
}

export function getBothesisChatConfiguration(): BothesisChatConfiguration | null {
  const dataMode = getBothesisDataMode();
  if (dataMode === "mock") {
    return {
      apiUrl: "mock://bothesis",
      tenantId: "tenant-northstar",
      userId: "user-maya-chen",
      dataMode,
    };
  }
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  const tenantId = process.env.NEXT_PUBLIC_BOTHESIS_TENANT_ID?.trim();
  const userId = process.env.NEXT_PUBLIC_BOTHESIS_USER_ID?.trim();
  if (!apiUrl || !tenantId || !userId) return null;
  return { apiUrl, tenantId, userId, dataMode };
}
