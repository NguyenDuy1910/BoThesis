import { redirect } from "next/navigation";

export default async function WorkflowGraphWorkspacePage({
  params,
}: {
  params: Promise<{ graphId: string }>;
}) {
  await params;
  redirect("/workflows");
}
