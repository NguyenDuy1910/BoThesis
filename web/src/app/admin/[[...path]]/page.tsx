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
  // Apps became a product-level surface. Preserve historical Admin links and
  // connector aliases without loading an extra Admin shell first.
  if (section === "apps-permissions" || section === "connectors" || section === "sources") {
    redirect("/apps");
  }

  return <AdminPage section={path.join("/")} />;
}
