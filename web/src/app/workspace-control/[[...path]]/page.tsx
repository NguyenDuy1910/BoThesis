import { redirect } from "next/navigation";

import { ControlPlanePage } from "@/modules/workspace-control/components/ControlPlanePage";

/** Sections that were folded into Knowledge and no longer address a page. */
const FOLDED_INTO_KNOWLEDGE = new Set([
  "collections",
  "knowledge-bases",
  "documents",
  "all-items",
  "items",
]);

export default async function ControlPlaneRoute({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = [] } = await params;

  // Collection and document management is one Knowledge section now. Redirect
  // on server so old link never renders control shell it will leave.
  if (path[0] && FOLDED_INTO_KNOWLEDGE.has(path[0])) redirect("/workspace-control/knowledge");

  return <ControlPlanePage section={path.join("/")} />;
}
