import { DocumentViewer } from "@/modules/knowledge/components/DocumentViewer";

export default async function KnowledgeItemPage({
  params,
}: {
  params: Promise<{ itemId: string }>;
}) {
  const { itemId } = await params;
  return <DocumentViewer itemId={itemId} />;
}
