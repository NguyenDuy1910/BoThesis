import { isMessageItem, isOutputTextPart, orderedTurnItems } from "./message-stream.ts";
import { DOCUMENT_CITATION_TYPE } from "./types.ts";
import type { CitationReference, CitationSpan, TurnState } from "./types";

export interface AnswerSource {
  id: string;
  title: string;
  itemId: string;
  chunkId: string;
  /** Primary internal viewer target. */
  internalUrl: string;
  /** Native source target, when the provider supplied one. */
  originalUrl?: string;
  locator?: string;
  origin?: string;
  /** Citations are annotations on answer content, so every entry is used. */
  used: true;
  spans: CitationSpan[];
}

/** Collect citations from output-text annotations, never from stream events. */
export function answerSources(turn: TurnState | undefined): AnswerSource[] {
  if (!turn) return [];
  const sources = new Map<string, AnswerSource>();
  const order: string[] = [];

  for (const { item } of orderedTurnItems(turn)) {
    if (!isMessageItem(item)) continue;
    for (const part of item.content) {
      if (!isOutputTextPart(part)) continue;
      for (const annotation of part.annotations) {
        if (annotation.type !== DOCUMENT_CITATION_TYPE || !annotation.citation) continue;
        const source = toAnswerSource(annotation.citation);
        if (!source) continue;
        const existing = sources.get(source.id);
        if (!existing) {
          sources.set(source.id, source);
          order.push(source.id);
        } else {
          sources.set(source.id, mergeSource(existing, source));
        }
      }
    }
  }
  return order.map((id) => sources.get(id)!);
}

function toAnswerSource(citation: CitationReference): AnswerSource | null {
  const itemId = citation.item_id?.trim();
  const chunkId = citation.chunk_id?.trim();
  if (!itemId || !chunkId) return null;
  const id = citation.id?.trim() || chunkId;
  const internalUrl = citation.internal_url?.trim()
    || `/knowledge/items/${encodeURIComponent(itemId)}?chunk=${encodeURIComponent(chunkId)}`;
  const originalUrl = citation.original_url?.trim() || citation.source?.url?.trim() || undefined;
  return {
    id,
    itemId,
    chunkId,
    title: citation.title?.trim() || citation.source?.provider?.trim() || "Untitled source",
    internalUrl,
    originalUrl,
    locator: locatorLabel(citation.spans ?? [], citation.section),
    origin: citation.source?.provider?.trim() || undefined,
    used: true,
    spans: citation.spans ?? [],
  };
}

function mergeSource(existing: AnswerSource, next: AnswerSource): AnswerSource {
  return {
    id: existing.id,
    itemId: existing.itemId,
    chunkId: existing.chunkId,
    title: next.title || existing.title,
    internalUrl: next.internalUrl || existing.internalUrl,
    originalUrl: next.originalUrl ?? existing.originalUrl,
    locator: next.locator ?? existing.locator,
    origin: next.origin ?? existing.origin,
    used: true,
    spans: next.spans.length ? next.spans : existing.spans,
  };
}

function locatorLabel(spans: CitationSpan[], section?: string | null): string | undefined {
  const pages = spans
    .map((span) => span.page)
    .filter((page): page is number => typeof page === "number");
  const page = pages.length ? (pages.length === 1 ? String(pages[0]) : `${pages[0]}–${pages[pages.length - 1]}`) : undefined;
  const values = [
    page === undefined
      ? undefined
      : `p. ${page}`,
    section?.trim() || undefined,
  ].filter((value): value is string => Boolean(value));
  return values.length ? values.join(" · ") : undefined;
}

export function sourcesLabel(sources: AnswerSource[]): string {
  return `${sources.length} ${sources.length === 1 ? "source" : "sources"}`;
}
