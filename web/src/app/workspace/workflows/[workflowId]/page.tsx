import { redirect } from "next/navigation";

export default async function WorkflowWorkspacePage({
  params,
  searchParams,
}: {
  params: Promise<{ workflowId: string }>;
  searchParams: Promise<{ thread?: string }>;
}) {
  await params;
  await searchParams;
  redirect("/workflows");
}
