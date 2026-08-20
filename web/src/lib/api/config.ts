export interface BothesisChatConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
}

export function getBothesisChatConfiguration(): BothesisChatConfiguration | null {
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  const tenantId = process.env.NEXT_PUBLIC_BOTHESIS_TENANT_ID?.trim();
  const userId = process.env.NEXT_PUBLIC_BOTHESIS_USER_ID?.trim();
  if (!apiUrl || !tenantId || !userId) return null;
  return { apiUrl, tenantId, userId };
}
