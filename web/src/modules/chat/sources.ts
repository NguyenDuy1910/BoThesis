import { isMessageItem, isOutputTextPart, orderedTurnItems } from "./message-stream.ts";
import { DOCUMENT_CITATION_TYPE } from "./types.ts";
import type { CitationReference, CitationSpan, TurnState } from "./types";

export interface AnswerSource {
  id: string;
  /** The stable one-based marker the reader clicks, in first-cited order. */
  index: number;
  title: string;
  itemId: string;
  chunkId: string;
  /** Primary internal viewer target. */
  internalUrl: string;
  /** Native source target, when the provider supplied one. */
  originalUrl?: string;
  locator?: string;
  origin?: string;
  /** The first cited page, when the source recorded one. */
  page?: number;
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
  // The backend numbers citations by first use so the inline chip and this
  // list always agree. First-appearance order here is the fallback for
  // conversations saved before citations carried a number.
  return order.map((id, position) => {
    const source = sources.get(id)!;
    return { ...source, index: source.index || position + 1 };
  });
}

function toAnswerSource(citation: CitationReference): AnswerSource | null {
  const itemId = citation.item_id?.trim();
  const chunkId = citation.chunk_id?.trim();
  if (!itemId || !chunkId) return null;
  const id = citation.id?.trim() || chunkId;
  const spans = citation.spans ?? [];
  const internalUrl = citation.internal_url?.trim()
    || `/knowledge/items/${encodeURIComponent(itemId)}?chunk=${encodeURIComponent(chunkId)}`;
  const originalUrl = citation.original_url?.trim() || citation.source?.url?.trim() || undefined;
  return {
    id,
    // Zero means unnumbered; collection order fills it in as the fallback.
    index: typeof citation.number === "number" && citation.number > 0
      ? citation.number
      : 0,
    itemId,
    chunkId,
    title: citation.title?.trim() || citation.source?.provider?.trim() || "Untitled source",
    internalUrl,
    originalUrl,
    locator: locatorLabel(citation, spans),
    origin: citation.source?.provider?.trim() || undefined,
    page: citedPage(citation, spans),
    used: true,
    spans,
  };
}

function mergeSource(existing: AnswerSource, next: AnswerSource): AnswerSource {
  return {
    id: existing.id,
    index: existing.index || next.index,
    itemId: existing.itemId,
    chunkId: existing.chunkId,
    title: next.title || existing.title,
    internalUrl: next.internalUrl || existing.internalUrl,
    originalUrl: next.originalUrl ?? existing.originalUrl,
    locator: next.locator ?? existing.locator,
    origin: next.origin ?? existing.origin,
    page: next.page ?? existing.page,
    used: true,
    spans: next.spans.length ? next.spans : existing.spans,
  };
}

/**
 * Pages come from spans when ingestion captured element geometry, and from the
 * chunk's page range otherwise. Retrieval carries the range even where span
 * geometry is not part of the indexed payload, so both are read.
 */
function citedPages(citation: CitationReference, spans: CitationSpan[]): number[] {
  const pages = spans
    .map((span) => span.page)
    .filter((page): page is number => typeof page === "number" && page >= 1);
  if (pages.length) return [...new Set(pages)].sort((left, right) => left - right);
  const start = citation.page_start;
  const end = citation.page_end ?? start;
  if (typeof start !== "number" || typeof end !== "number") return [];
  return start === end ? [start] : [start, end];
}

function citedPage(citation: CitationReference, spans: CitationSpan[]): number | undefined {
  return citedPages(citation, spans)[0];
}

function locatorLabel(
  citation: CitationReference,
  spans: CitationSpan[],
): string | undefined {
  const pages = citedPages(citation, spans);
  const page = pages.length
    ? (pages.length === 1 ? String(pages[0]) : `${pages[0]}–${pages[pages.length - 1]}`)
    : undefined;
  const values = [
    page === undefined ? undefined : `p. ${page}`,
    citation.section?.trim() || undefined,
  ].filter((value): value is string => Boolean(value));
  return values.length ? values.join(" · ") : undefined;
}

export function sourcesLabel(sources: readonly AnswerSource[]): string {
  return `${sources.length} ${sources.length === 1 ? "source" : "sources"}`;
}
