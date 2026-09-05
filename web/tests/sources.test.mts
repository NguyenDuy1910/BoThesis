import assert from "node:assert/strict";
import test from "node:test";

import { answerSources, sourcesLabel } from "../src/modules/chat/sources.ts";
import { resolveHighlightRange } from "../src/modules/knowledge/highlight.ts";
import { DOCUMENT_CITATION_TYPE } from "../src/modules/chat/types.ts";
import type { OutputTextAnnotation, TurnState } from "../src/modules/chat/types.ts";

test("collects a citation once when it arrives in annotation and final content", () => {
  const citation = annotation({
    id: "e1",
    item_id: "item-1",
    chunk_id: "chunk-1",
    title: "Access Policy",
    original_url: "https://kb/e1",
  });
  const sources = answerSources(turnWithAnnotations([citation, citation]));

  assert.equal(sources.length, 1);
  assert.equal(sources[0]?.title, "Access Policy");
  assert.equal(sources[0]?.originalUrl, "https://kb/e1");
  assert.equal(sources[0]?.internalUrl, "/knowledge/items/item-1?chunk=chunk-1");
});

test("keeps citations in content order", () => {
  const sources = answerSources(turnWithAnnotations([
    annotation({ id: "first", item_id: "item-1", chunk_id: "first", title: "Decision Memo" }),
    annotation({ id: "second", item_id: "item-2", chunk_id: "second", title: "Background" }),
  ]));

  assert.deepEqual(sources.map((source) => source.id), ["first", "second"]);
});

test("an internal citation always links to the exact viewer target", () => {
  const [source] = answerSources(turnWithAnnotations([
    annotation({ id: "secret", item_id: "item-3", chunk_id: "secret", title: "Board Pack" }),
  ]));

  assert.equal(source?.internalUrl, "/knowledge/items/item-3?chunk=secret");
});

test("page and section become one locator", () => {
  const [source] = answerSources(turnWithAnnotations([
    annotation({ id: "source", item_id: "item-4", chunk_id: "source", spans: [{ page: 12 }], section: "Controls" }),
  ]));

  assert.equal(source?.locator, "p. 12 · Controls");
});

test("non-citation annotations are ignored", () => {
  assert.deepEqual(answerSources(turnWithAnnotations([{ type: "file_path", path: "/tmp/a" }])), []);
});

test("the summary counts cited sources", () => {
  assert.equal(sourcesLabel(answerSources(turnWithAnnotations([annotation({ id: "a", item_id: "item-a", chunk_id: "a" })]))), "1 source");
  assert.equal(
    sourcesLabel(answerSources(turnWithAnnotations([
      annotation({ id: "a", item_id: "item-a", chunk_id: "a" }),
      annotation({ id: "b", item_id: "item-b", chunk_id: "b" }),
    ]))),
    "2 sources",
  );
});

test("element offsets highlight the exact retrieved chunk text", () => {
  const element = "The partition leader handles all reads and writes.";
  const chunk = "leader handles all reads";
  const start = element.indexOf(chunk);

  assert.deepEqual(
    resolveHighlightRange(element, {
      chunk_text: chunk,
      start_offset: start,
      end_offset: start + chunk.length,
    }),
    { start, end: start + chunk.length },
  );
});

test("highlighting falls back to matching normalized evidence text", () => {
  assert.deepEqual(
    resolveHighlightRange("Intro\nExact cited paragraph\nOutro", {
      chunk_text: "Exact cited paragraph",
      start_offset: 0,
      end_offset: 4,
    }),
    { start: 6, end: 27 },
  );
});

test("multi-span citations highlight each normalized element independently", () => {
  const citation = {
    chunk_text: "one\n\ntwo",
    spans: [
      { element_id: "p1", start_offset: 0, end_offset: 3 },
      { element_id: "p2", start_offset: 0, end_offset: 3 },
    ],
  };

  assert.deepEqual(resolveHighlightRange("one", citation, citation.spans[0]), { start: 0, end: 3 });
  assert.deepEqual(resolveHighlightRange("two", citation, citation.spans[1]), { start: 0, end: 3 });
});

test("citation markers are numbered once, in the order they were first cited", () => {
  const first = annotation({ id: "source-1111", item_id: "item-1", chunk_id: "c1" });
  const second = annotation({ id: "source-2222", item_id: "item-2", chunk_id: "c2" });
  const sources = answerSources(turnWithAnnotations([first, second, first]));

  assert.deepEqual(sources.map((source) => source.index), [1, 2]);
  assert.deepEqual(sources.map((source) => source.id), ["source-1111", "source-2222"]);
});

test("a cited page is read from the chunk page range when spans carry no geometry", () => {
  // Retrieval supplies the chunk's page range; span geometry is resolved from
  // canonical storage only once the citation is opened.
  const sources = answerSources(turnWithAnnotations([
    annotation({
      id: "source-1111",
      item_id: "item-1",
      chunk_id: "c1",
      section: "Annual leave",
      page_start: 7,
      page_end: 9,
      spans: [],
    }),
  ]));

  assert.equal(sources[0]?.page, 7);
  assert.equal(sources[0]?.locator, "p. 7\u20139 \u00b7 Annual leave");
});

test("span pages take precedence over the chunk page range", () => {
  const sources = answerSources(turnWithAnnotations([
    annotation({
      id: "source-1111",
      item_id: "item-1",
      chunk_id: "c1",
      page_start: 7,
      page_end: 9,
      spans: [{ page: 8 }],
    }),
  ]));

  assert.equal(sources[0]?.page, 8);
  assert.equal(sources[0]?.locator, "p. 8");
});

test("the backend number drives the chip and the summary list alike", () => {
  // The answer cites its second retrieved source first, so numbering follows
  // first use — not retrieval order.
  const sources = answerSources(turnWithAnnotations([
    annotation({ id: "ref_2", reference: "ref_2", number: 1, item_id: "i2", chunk_id: "c2" }),
    annotation({ id: "ref_1", reference: "ref_1", number: 2, item_id: "i1", chunk_id: "c1" }),
    annotation({ id: "ref_2", reference: "ref_2", number: 1, item_id: "i2", chunk_id: "c2" }),
  ]));

  // A repeated citation is one entry, keeping its number.
  assert.equal(sources.length, 2);
  assert.deepEqual(sources.map((source) => [source.id, source.index]), [
    ["ref_2", 1],
    ["ref_1", 2],
  ]);
});

test("conversations saved before numbering still resolve in order", () => {
  const sources = answerSources(turnWithAnnotations([
    annotation({ id: "a", item_id: "i1", chunk_id: "c1" }),
    annotation({ id: "b", item_id: "i2", chunk_id: "c2" }),
  ]));

  assert.deepEqual(sources.map((source) => source.index), [1, 2]);
});

function annotation(citation: NonNullable<OutputTextAnnotation["citation"]>): OutputTextAnnotation {
  return { type: DOCUMENT_CITATION_TYPE, citation };
}

function turnWithAnnotations(annotations: OutputTextAnnotation[]): TurnState {
  return {
    id: "turn-1",
    status: "completed",
    responseOrder: ["response-1"],
    responses: {
      "response-1": {
        id: "response-1",
        status: "completed",
        itemOrder: ["message-1"],
        items: {
          "message-1": {
            type: "message",
            id: "message-1",
            role: "assistant",
            status: "completed",
            content: [{ type: "output_text", text: "Grounded answer.", annotations }],
          },
        },
      },
    },
  };
}
