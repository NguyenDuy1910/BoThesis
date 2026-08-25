import type { ConversationAdapter } from "@/modules/chat/conversations";
import {
  DOCUMENT_CITATION_TYPE,
  type CachedChatMessage,
  type ConversationDocument,
  type MessageItem,
  type ResponseStreamEvent,
  type TurnState,
} from "@/modules/chat/types";
import type { ChatConnector } from "@/modules/connectors/types";

const citation = {
  id: "citation-access-policy",
  item_id: "doc-access-policy",
  chunk_id: "chunk-access-review",
  title: "Enterprise Access Control Policy",
  section: "Quarterly access reviews",
  section_path: ["Identity governance", "Quarterly access reviews"],
  spans: [{ page: 8, element_id: "policy-review", start_offset: 0, end_offset: 188 }],
  source: { connector_id: "conn-files-governed", provider: "file", external_id: "policy-2026", url: "https://northstar.example/policies/access-control" },
  internal_url: "/knowledge/items/doc-access-policy?chunk=chunk-access-review",
  original_url: "https://northstar.example/policies/access-control",
};

export async function mockStreamAgentResponse(
  message: string,
  options: { signal: AbortSignal; onEvent: (event: ResponseStreamEvent) => void },
) {
  const responseId = `mock-response-${Date.now()}`;
  const itemId = `mock-message-${Date.now()}`;
  const answer = answerFor(message);
  const annotation = {
    type: DOCUMENT_CITATION_TYPE,
    start_index: 0,
    end_index: Math.min(answer.length, 188),
    citation,
  };
  const messageItem: MessageItem = {
    id: itemId,
    type: "message",
    role: "assistant",
    status: "in_progress",
    phase: "final_answer",
    content: [{ type: "output_text", text: "", annotations: [] }],
  };
  const send = async (event: ResponseStreamEvent, delay = 90) => {
    await abortableDelay(options.signal, delay);
    options.onEvent(event);
  };

  await send({ type: "response.created", response: { id: responseId, status: "in_progress", output: [] } }, 70);
  await send({ type: "response.output_item.added", output_index: 0, item: messageItem });
  await send({ type: "response.content_part.added", item_id: itemId, output_index: 0, content_index: 0, part: { type: "output_text", text: "", annotations: [] } }, 40);
  const chunks = answer.match(/.{1,72}(?:\s|$)/g) ?? [answer];
  for (const delta of chunks) {
    await send({ type: "response.output_text.delta", item_id: itemId, output_index: 0, content_index: 0, delta }, 45);
  }
  await send({ type: "response.output_text.annotation.added", item_id: itemId, output_index: 0, content_index: 0, annotation_index: 0, annotation }, 30);
  const completed: MessageItem = { ...messageItem, status: "completed", content: [{ type: "output_text", text: answer, annotations: [annotation] }] };
  await send({ type: "response.output_item.done", output_index: 0, item: completed }, 30);
  await send({ type: "response.completed", response: { id: responseId, status: "completed", output: [completed] } }, 30);
}

export async function mockChatConnectors(signal?: AbortSignal): Promise<ChatConnector[]> {
  await abortableDelay(signal, 120);
  return [
    { id: "101", provider: "confluence", display_name: "Company Confluence", status: "active", capabilities: ["search", "citations", "permissions"] },
    { id: "102", provider: "file", display_name: "Governed uploads", status: "active", capabilities: ["search", "citations", "permissions"] },
  ];
}

export async function mockUploadConversationDocument(
  file: File,
  options: { signal: AbortSignal; onProgress?: (status: "starting" | "uploading" | "validating") => void },
): Promise<ConversationDocument> {
  options.onProgress?.("starting");
  await abortableDelay(options.signal, 100);
  options.onProgress?.("uploading");
  await abortableDelay(options.signal, 180);
  options.onProgress?.("validating");
  await abortableDelay(options.signal, 120);
  return {
    id: `mock-upload-${crypto.randomUUID()}`,
    fileName: file.name,
    contentType: file.type || "application/octet-stream",
    sizeBytes: file.size,
    mode: file.size <= 20 * 1024 * 1024 ? "direct" : "indexed",
    status: "available",
  };
}

export async function seedMockConversationHistory(adapter: ConversationAdapter) {
  const storageKey = "bothesis-mock-conversations-seeded:v1";
  if (window.localStorage.getItem(storageKey)) return;
  const existing = await adapter.listConversations();
  if (existing.length) {
    window.localStorage.setItem(storageKey, "existing");
    return;
  }
  const first = await adapter.createConversation("Weekly leadership risk review", "mock-conversation-risk");
  await adapter.saveConversationMessages(first.id, seededMessages(
    "What risks should leadership review this week?",
    "Leadership should review three items this week:\n\n1. **Finance ingestion is blocked** by a schema-validation failure in the Q4 Operating Plan.\n2. **Customer Operations is only partially indexed** while the legacy wiki connection recovers.\n3. **One Security & Compliance access request is pending**, so the requester cannot yet use that collection in chat.\n\nThe access policy requires collection permissions to be resolved before retrieval results reach the assistant.",
  ));
  const second = await adapter.createConversation("Access review briefing", "mock-conversation-access");
  await adapter.saveConversationMessages(second.id, seededMessages(
    "Summarize our quarterly access review policy.",
    "Collection owners must review membership and explicit grants each quarter. Remove stale access through the governed lifecycle, preserve the audit trail, and verify that deny rules take precedence before content is retrieved.",
  ));
  window.localStorage.setItem(storageKey, "seeded");
}

function seededMessages(question: string, answer: string): CachedChatMessage[] {
  return [
    { id: `mock-user-${question.slice(0, 8)}`, role: "user", content: question, parts: [{ type: "text", text: question, state: "done" }], createdAt: Date.now() - 60_000 },
    { id: `mock-assistant-${question.slice(0, 8)}`, role: "assistant", content: answer, parts: [], turn: completedTurn(answer), createdAt: Date.now() - 45_000 },
  ];
}

function completedTurn(answer: string): TurnState {
  const annotation = { type: DOCUMENT_CITATION_TYPE, start_index: 0, end_index: Math.min(answer.length, 188), citation };
  const item: MessageItem = { id: "mock-seeded-answer", type: "message", role: "assistant", status: "completed", phase: "final_answer", content: [{ type: "output_text", text: answer, annotations: [annotation] }] };
  return { id: "mock-seeded-turn", status: "completed", responses: { "mock-seeded-response": { id: "mock-seeded-response", status: "completed", items: { "mock-seeded-answer": item }, itemOrder: ["mock-seeded-answer"] } }, responseOrder: ["mock-seeded-response"], currentResponseId: "mock-seeded-response" };
}

function answerFor(message: string) {
  const topic = message.toLowerCase();
  if (topic.includes("risk")) {
    return "The current review queue has three material signals: Finance Planning has a failed schema validation, Customer Operations is still indexing, and one Security & Compliance access request is pending. I would assign owners today and re-check sync health before the leadership briefing. The access-control evidence below confirms that permissions must be enforced before retrieval.";
  }
  if (topic.includes("access") || topic.includes("permission")) {
    return "Access is enforced at the tenant and collection boundaries before search results reach the assistant. Quarterly reviewers should verify group membership, explicit grants, and deny rules, then retain the decision in the audit log. The cited policy contains the controlling review requirement.";
  }
  return "Based on the governed demo workspace, the highest-priority follow-up is the failed Finance Planning ingestion, followed by the partially indexed Customer Operations collection. Product & Engineering and Security & Compliance are search-ready. This mock response includes an inspectable citation so the complete review workflow can be tested.";
}

function abortableDelay(signal?: AbortSignal, duration = 100) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("The request was cancelled.", "AbortError")); return; }
    const timer = setTimeout(resolve, duration);
    signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("The request was cancelled.", "AbortError")); }, { once: true });
  });
}
