import { KnowledgeWorkspace } from "@/modules/knowledge/components/KnowledgeWorkspace";

export default async function KnowledgeCollectionPage({
  params,
}: {
  params: Promise<{ collectionId: string }>;
}) {
  const { collectionId } = await params;
  return <KnowledgeWorkspace collectionId={collectionId} />;
}
