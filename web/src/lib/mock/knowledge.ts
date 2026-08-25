import type { KnowledgeCitationResponse, KnowledgeItemViewer } from "@/modules/knowledge/types";

const elements = [
  {
    element_id: "policy-purpose",
    text: "This policy establishes the controls used to grant, review, and remove access to Northstar enterprise knowledge. Controls apply across tenant, collection, connector, document, and retrieval boundaries.",
    page: 2,
    section: "Purpose",
    section_path: ["Access Control Policy", "Purpose"],
    anchor: "purpose",
  },
  {
    element_id: "policy-review",
    text: "Collection owners must review group membership, explicit user grants, and deny rules at least once each quarter. Stale access must be removed through the governed lifecycle, and the decision must remain available in the administration audit log.",
    page: 8,
    section: "Quarterly access reviews",
    section_path: ["Identity governance", "Quarterly access reviews"],
    anchor: "quarterly-reviews",
  },
  {
    element_id: "policy-enforcement",
    text: "Permission filters are evaluated before retrieval results, document excerpts, or citations reach an assistant. A deny rule takes precedence over an allow rule. Source lineage remains attached to every indexed item.",
    page: 9,
    section: "Retrieval enforcement",
    section_path: ["Identity governance", "Retrieval enforcement"],
    anchor: "retrieval-enforcement",
  },
];

const citation = {
  section: "Quarterly access reviews",
  section_path: ["Identity governance", "Quarterly access reviews"],
  anchor: "quarterly-reviews",
  spans: [{ page: 8, element_id: "policy-review", start_offset: 0, end_offset: elements[1].text.length }],
};

export async function mockKnowledgeViewer(itemId: string, chunkId?: string, signal?: AbortSignal): Promise<KnowledgeItemViewer> {
  await delay(signal);
  return {
    item_id: itemId,
    title: itemId === "doc-access-policy" ? "Enterprise Access Control Policy" : "Governed knowledge document",
    content_type: "application/pdf",
    external_url: "https://northstar.example/policies/access-control",
    document_url: null,
    elements,
    focus: chunkId ? { chunk_id: chunkId, chunk_text: elements[1].text, citation } : null,
  };
}

export async function mockKnowledgeCitation(itemId: string, chunkId: string, signal?: AbortSignal): Promise<KnowledgeCitationResponse> {
  await delay(signal);
  return {
    item_id: itemId,
    chunk_id: chunkId,
    title: "Enterprise Access Control Policy",
    content_type: "application/pdf",
    document_url: null,
    external_url: "https://northstar.example/policies/access-control",
    citation,
  };
}

function delay(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("The request was cancelled.", "AbortError")); return; }
    const timer = setTimeout(resolve, 130);
    signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("The request was cancelled.", "AbortError")); }, { once: true });
  });
}
