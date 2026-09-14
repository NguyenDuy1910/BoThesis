import { redirect } from "next/navigation";

import { AdminPage } from "@/modules/admin/components/AdminPage";

/** Sections that were folded into Knowledge and no longer address a page. */
const FOLDED_INTO_KNOWLEDGE = new Set([
  "collections",
  "knowledge-bases",
  "documents",
  "all-items",
  "items",
]);

export default async function AdminRoute({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = [] } = await params;

  // Collection and document management is one Knowledge section now. Redirect
  // on the server so an old link never renders an Admin shell it will leave.
  if (path[0] && FOLDED_INTO_KNOWLEDGE.has(path[0])) redirect("/admin/knowledge");

  return <AdminPage section={path.join("/")} />;
}
