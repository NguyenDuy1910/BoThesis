/**
 * Streaming markdown geometry: where accumulated assistant text may be cut, and
 * how much of it to put on screen per paint.
 *
 * The renderer parses the finished prefix once per completed block and re-parses
 * only the arriving tail, so both decisions live here as pure functions.
 */

/** One reveal commit per interval, so markdown is re-parsed ~30x/s at most. */
export const REVEAL_COMMIT_INTERVAL_MS = 32;

/** Enough per commit that words flow, not so much that a burst dumps at once. */
const REVEAL_MIN_CHARACTERS = 12;
const REVEAL_MAX_CHARACTERS = 320;
/** Reveal a share of the backlog each commit, so a burst always catches up. */
const REVEAL_BACKLOG_DIVISOR = 3;

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})/;
const LIST_MARKER = /^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)/;
// A reference definition resolves links and footnotes anywhere in the same
// document, so text that uses them is only correct parsed as a single piece.
const REFERENCE_DEFINITION = /^ {0,3}\[[^\]]*\]:/m;

export interface StreamingMarkdownSplit {
  /** Blocks that are finished: parse once, then leave alone. */
  stable: string;
  /** The block still being written, plus anything that cannot be cut off yet. */
  tail: string;
}

/**
 * Split accumulated markdown into a finished prefix and the arriving tail.
 *
 * The two halves are parsed by separate markdown roots, so the cut may only
 * fall where a markdown block actually ends. Cutting inside a block changes
 * what the text means: a fenced code block loses its terminator and swallows
 * the following prose, a loose list becomes several lists, and an indented list
 * continuation becomes a code block. Only a blank line followed by a new
 * top-level block is safe, and everything after the last one stays in the tail.
 */
export function splitStreamingMarkdown(content: string): StreamingMarkdownSplit {
  const boundary = content ? stableMarkdownBoundary(content) : 0;
  return boundary > 0
    ? { stable: content.slice(0, boundary), tail: content.slice(boundary) }
    : { stable: "", tail: content };
}

function stableMarkdownBoundary(content: string): number {
  if (REFERENCE_DEFINITION.test(content)) return 0;

  let boundary = 0;
  let offset = 0;
  let openFence: string | null = null;
  let openMath = false;
  let openList = false;
  let previousLineIsBlank = false;

  for (const line of content.split("\n")) {
    const isBlank = !line.trim();
    const isIndented = /^[ \t]/.test(line);
    const isListItem = LIST_MARKER.test(line);
    if (
      previousLineIsBlank
      && !isBlank
      && !openFence
      && !openMath
      // Indented text continues the item or code block above the blank line.
      && !isIndented
      // A list item after a blank line continues a loose list; splitting it off
      // would render one list as several.
      && !(isListItem && openList)
    ) {
      boundary = offset;
    }

    if (openFence) {
      if (closesFence(line, openFence)) openFence = null;
    } else {
      const fence = FENCE_OPEN.exec(line);
      if (fence) openFence = fence[1];
      else if (countDisplayMathMarkers(line) % 2 === 1) openMath = !openMath;
    }
    if (!openFence && !isBlank) {
      // A list stays open across its own blank lines and indented continuations.
      openList = isListItem || (openList && isIndented);
    }

    // A blank line inside a fence or a display-math block separates nothing.
    previousLineIsBlank = isBlank && !openFence && !openMath;
    offset += line.length + 1;
  }

  return boundary;
}

function closesFence(line: string, openFence: string): boolean {
  const closing = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line);
  return Boolean(
    closing
    && closing[1][0] === openFence[0]
    && closing[1].length >= openFence.length,
  );
}

function countDisplayMathMarkers(line: string): number {
  return line.split("$$").length - 1;
}

/**
 * How much of ``text`` to show after the next commit.
 *
 * The step scales with the backlog, so a fast burst eases onto screen instead
 * of dumping and still finishes within a few hundred milliseconds — the client
 * paces paints, it never waits on text it already has.
 */
export function nextRevealLength(text: string, revealedLength: number): number {
  const remaining = text.length - revealedLength;
  if (remaining <= 0) return text.length;
  const step = Math.min(
    REVEAL_MAX_CHARACTERS,
    Math.max(REVEAL_MIN_CHARACTERS, Math.ceil(remaining / REVEAL_BACKLOG_DIVISOR)),
  );
  const revealed = revealedLength + step;
  if (revealed >= text.length) return text.length;
  // Never leave a half-typed word on screen, unless one token is longer than a
  // whole commit and snapping back would stall the reveal.
  const boundary = wordBoundaryAtOrBefore(text, revealed);
  return boundary > revealedLength ? boundary : revealed;
}

function wordBoundaryAtOrBefore(text: string, position: number): number {
  for (let index = position; index > 0; index -= 1) {
    const character = text[index - 1];
    if (character === " " || character === "\n" || character === "\t") return index;
  }
  return 0;
}
