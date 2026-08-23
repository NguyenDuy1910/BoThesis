import { AdminPage } from "@/modules/admin/components/AdminPage";

export default async function AdminRoute({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = ["overview"] } = await params;
  return <AdminPage section={path.join("/")} />;
}
