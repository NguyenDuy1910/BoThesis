import { isMessageItem, isOutputTextPart, orderedTurnItems } from "./message-stream.ts";
import type { CitationReference, TurnState } from "./types";

export interface AnswerSource {
  id: string;
  title: string;
  /** Absent when the source carries no openable location, or is restricted. */
  url?: string;
  /** Page / section locator, shown next to the title. */
  locator?: string;
  origin?: string;
  /** Citations are annotations on answer content, so every entry is used. */
  used: true;
  /** Citations outside the reader's access are never linked. */
  restricted: boolean;
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
        if (annotation.type !== "citation" || !annotation.citation) continue;
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
  const id = citation.id?.trim() || citation.document_id?.trim();
  if (!id) return null;
  const restricted = citation.restricted === true;
  const url = citation.uri?.trim();
  return {
    id,
    title: citation.title?.trim() || citation.source?.trim() || "Untitled source",
    url: restricted || !url ? undefined : url,
    locator: locatorLabel(citation.page, citation.section),
    origin: citation.source?.trim() || undefined,
    used: true,
    restricted,
  };
}

function mergeSource(existing: AnswerSource, next: AnswerSource): AnswerSource {
  const restricted = existing.restricted || next.restricted;
  return {
    id: existing.id,
    title: next.title || existing.title,
    url: restricted ? undefined : next.url ?? existing.url,
    locator: next.locator ?? existing.locator,
    origin: next.origin ?? existing.origin,
    used: true,
    restricted,
  };
}

function locatorLabel(page?: string | number | null, section?: string | null): string | undefined {
  const values = [
    section?.trim() || undefined,
    page === undefined || page === null || String(page).trim() === ""
      ? undefined
      : `p. ${String(page).trim()}`,
  ].filter((value): value is string => Boolean(value));
  return values.length ? values.join(" · ") : undefined;
}

export function sourcesLabel(sources: AnswerSource[]): string {
  return `${sources.length} ${sources.length === 1 ? "source" : "sources"}`;
}
