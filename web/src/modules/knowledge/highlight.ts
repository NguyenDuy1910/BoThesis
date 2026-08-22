export interface HighlightFocus {
  chunk_text: string;
  section?: string | null;
  spans?: HighlightSpan[];
  start_offset?: number | null;
  end_offset?: number | null;
}

export interface HighlightSpan {
  element_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
}

export interface HighlightRange {
  start: number;
  end: number;
}

/**
 * Prefer the persisted element-local offsets, but verify them against the
 * evidence text before painting. The text fallback keeps older normalized
 * renderings safe without changing the citation contract.
 */
export function resolveHighlightRange(
  elementText: string,
  focus: HighlightFocus,
  span?: HighlightSpan,
): HighlightRange | undefined {
  const start = span?.start_offset ?? focus.start_offset;
  const end = span?.end_offset ?? focus.end_offset;
  if (
    typeof start === "number"
    && typeof end === "number"
    && start >= 0
    && end >= start
    && end <= elementText.length
  ) {
    if (span || elementText.slice(start, end) === focus.chunk_text) {
      return { start, end };
    }
  }
  if (span) {
    return undefined;
  }
  const match = elementText.indexOf(focus.chunk_text);
  return match < 0
    ? undefined
    : { start: match, end: match + focus.chunk_text.length };
}
