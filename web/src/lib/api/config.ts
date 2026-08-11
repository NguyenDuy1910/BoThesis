export interface BothesisChatConfiguration {
  apiUrl: string;
  tenantId: string;
  userId: string;
  roles: string[];
}

export function getBothesisChatConfiguration(): BothesisChatConfiguration | null {
  const apiUrl = process.env.NEXT_PUBLIC_BOTHESIS_API_URL?.replace(/\/$/, "");
  const tenantId = process.env.NEXT_PUBLIC_BOTHESIS_TENANT_ID?.trim();
  const userId = process.env.NEXT_PUBLIC_BOTHESIS_USER_ID?.trim();
  const roles = (process.env.NEXT_PUBLIC_BOTHESIS_ROLES ?? "")
    .split(",")
    .map((role) => role.trim())
    .filter(Boolean);

  if (!apiUrl || !tenantId || !userId || roles.length === 0) return null;
  return { apiUrl, tenantId, userId, roles };
}
