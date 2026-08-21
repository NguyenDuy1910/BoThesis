import type { ChatMessagePart } from "./types";

export interface AnswerSource {
  id: string;
  title: string;
  /** Absent when the source carries no openable location, or is restricted. */
  url?: string;
  /** Page / section locator, shown next to the title. */
  locator?: string;
  origin?: string;
  snippet?: string;
  /** The answer cited this source, as opposed to merely retrieving it. */
  used: boolean;
  /** Retrieved but outside the caller's permissions — never linked. */
  restricted: boolean;
}

type SourcePart = Extract<ChatMessagePart, { type: "data-source" }>;

/**
 * Collect the evidence behind one assistant turn.
 *
 * The stream emits an ``evidence`` item when a source is found and again when
 * the answer actually cites it, so the same id arrives more than once and the
 * later "Used" state must win. Cited sources are listed first — that is the set
 * a reader is checking the answer against.
 */
export function answerSources(parts: ChatMessagePart[]): AnswerSource[] {
  const byId = new Map<string, AnswerSource>();
  const order: string[] = [];
  const scores = new Map<string, number>();

  for (const part of parts) {
    if (part.type !== "data-source") continue;
    const source = toAnswerSource(part);
    if (!source) continue;
    const existing = byId.get(source.id);
    if (!existing) {
      order.push(source.id);
      byId.set(source.id, source);
    } else {
      byId.set(source.id, mergeSource(existing, source));
    }
    const score = part.data.relevanceScore;
    if (typeof score === "number" && Number.isFinite(score)) {
      scores.set(source.id, Math.max(scores.get(source.id) ?? score, score));
    }
  }

  return order
    .map((id, index) => ({ source: byId.get(id)!, index }))
    .sort((a, b) => {
      if (a.source.used !== b.source.used) return a.source.used ? -1 : 1;
      const scoreDelta = (scores.get(b.source.id) ?? 0) - (scores.get(a.source.id) ?? 0);
      if (scoreDelta !== 0) return scoreDelta;
      return a.index - b.index;
    })
    .map(({ source }) => source);
}

function toAnswerSource(part: SourcePart): AnswerSource | null {
  const { data } = part;
  const id = data.id?.trim();
  if (!id) return null;
  const restricted = data.restricted === true || data.status === "Restricted";
  const url = data.url?.trim();
  return {
    id,
    title: data.title?.trim() || untitledLabel(data.source, data.domain),
    url: restricted || !url ? undefined : url,
    locator: locatorLabel(data.page, data.section),
    origin: data.source?.trim() || data.domain?.trim() || undefined,
    snippet: data.snippet?.trim() || undefined,
    used: data.status === "Used",
    restricted,
  };
}

/** Later events only add information; "Used" and a real URL are never lost. */
function mergeSource(existing: AnswerSource, next: AnswerSource): AnswerSource {
  const restricted = existing.restricted || next.restricted;
  return {
    id: existing.id,
    title: next.title || existing.title,
    url: restricted ? undefined : next.url ?? existing.url,
    locator: next.locator ?? existing.locator,
    origin: next.origin ?? existing.origin,
    snippet: next.snippet ?? existing.snippet,
    used: existing.used || next.used,
    restricted,
  };
}

function locatorLabel(page?: string, section?: string): string | undefined {
  const parts = [
    section?.trim() || undefined,
    page?.trim() ? `p. ${page.trim()}` : undefined,
  ].filter((value): value is string => Boolean(value));
  return parts.length ? parts.join(" · ") : undefined;
}

function untitledLabel(source?: string, domain?: string): string {
  return source?.trim() || domain?.trim() || "Untitled source";
}

export function sourcesLabel(sources: AnswerSource[]): string {
  const cited = sources.filter((source) => source.used).length;
  if (cited > 0) return `${cited} ${cited === 1 ? "source" : "sources"}`;
  return `${sources.length} ${sources.length === 1 ? "source" : "sources"} reviewed`;
}
