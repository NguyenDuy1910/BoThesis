import { AdminPage } from "@/modules/admin/components/AdminPage";
import { redirect } from "next/navigation";

export default async function AdminRoute({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = [] } = await params;
  const [section, collectionId] = path;

  // Collection and document management now lives in the Figma-aligned
  // Knowledge workspace. Keep published URLs usable without rendering the
  // retired Admin pages (or their surrounding Admin shell) first.
  if (section === "collections" || section === "knowledge-bases") {
    redirect(
      collectionId
        ? `/knowledge/collections/${encodeURIComponent(collectionId)}`
        : "/knowledge",
    );
  }
  if (section === "documents" || section === "all-items" || section === "items") {
    redirect("/knowledge");
  }

  return <AdminPage section={path.join("/")} />;
}
