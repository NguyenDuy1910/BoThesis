import { AdminUnavailablePage } from "@/modules/admin/components/AdminUnavailablePage";

export default async function AdminRoute({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = ["overview"] } = await params;
  return <AdminUnavailablePage section={path.join("/")} />;
}
