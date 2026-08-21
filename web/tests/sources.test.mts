import assert from "node:assert/strict";
import test from "node:test";

import { answerSources, sourcesLabel } from "../src/modules/chat/sources.ts";
import type { ChatMessagePart } from "../src/modules/chat/types.ts";

function sourcePart(
  data: Partial<Extract<ChatMessagePart, { type: "data-source" }>["data"]> & { id: string },
): ChatMessagePart {
  return {
    type: "data-source",
    id: data.id,
    data: { title: "Untitled", ...data },
  };
}

test("a source found and later cited collapses into one cited row", () => {
  const sources = answerSources([
    sourcePart({ id: "e1", title: "Access Policy", status: "Found" }),
    sourcePart({ id: "e1", title: "Access Policy", status: "Used", url: "https://kb/e1" }),
  ]);

  assert.equal(sources.length, 1);
  assert.equal(sources[0]?.used, true);
  assert.equal(sources[0]?.url, "https://kb/e1");
});

test("cited sources sort ahead of merely retrieved ones", () => {
  const sources = answerSources([
    sourcePart({ id: "found", title: "Background", status: "Found" }),
    sourcePart({ id: "cited", title: "Decision Memo", status: "Used" }),
  ]);

  assert.deepEqual(sources.map((source) => source.id), ["cited", "found"]);
});

test("higher relevance wins among sources of equal standing", () => {
  const sources = answerSources([
    sourcePart({ id: "low", status: "Found", relevanceScore: 0.2 }),
    sourcePart({ id: "high", status: "Found", relevanceScore: 0.9 }),
  ]);

  assert.deepEqual(sources.map((source) => source.id), ["high", "low"]);
});

test("a restricted source is listed but never linked", () => {
  const [source] = answerSources([
    sourcePart({ id: "secret", title: "Board Pack", url: "https://kb/secret", restricted: true }),
  ]);

  assert.equal(source?.restricted, true);
  assert.equal(source?.url, undefined);
});

test("restriction survives a later unrestricted event for the same source", () => {
  const [source] = answerSources([
    sourcePart({ id: "s", url: "https://kb/s", restricted: true }),
    sourcePart({ id: "s", url: "https://kb/s", status: "Used" }),
  ]);

  assert.equal(source?.restricted, true);
  assert.equal(source?.url, undefined);
});

test("page and section become one locator", () => {
  const [source] = answerSources([
    sourcePart({ id: "s", page: "12", section: "Controls" }),
  ]);

  assert.equal(source?.locator, "Controls · p. 12");
});

test("non-source parts and blank ids are ignored", () => {
  assert.deepEqual(
    answerSources([
      { type: "text", text: "hello", state: "done" },
      sourcePart({ id: "  " }),
    ]),
    [],
  );
});

test("the summary counts citations, and falls back to what was reviewed", () => {
  assert.equal(
    sourcesLabel(answerSources([sourcePart({ id: "a", status: "Used" })])),
    "1 source",
  );
  assert.equal(
    sourcesLabel(answerSources([
      sourcePart({ id: "a", status: "Used" }),
      sourcePart({ id: "b", status: "Used" }),
    ])),
    "2 sources",
  );
  assert.equal(
    sourcesLabel(answerSources([
      sourcePart({ id: "a", status: "Found" }),
      sourcePart({ id: "b", status: "Found" }),
    ])),
    "2 sources reviewed",
  );
});
