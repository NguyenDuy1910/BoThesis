import assert from "node:assert/strict";
import test from "node:test";

import { answerSources, sourcesLabel } from "../src/modules/chat/sources.ts";
import { DOCUMENT_CITATION_TYPE } from "../src/modules/chat/types.ts";
import type { OutputTextAnnotation, TurnState } from "../src/modules/chat/types.ts";

test("collects a citation once when it arrives in annotation and final content", () => {
  const citation = annotation({ id: "e1", title: "Access Policy", uri: "https://kb/e1" });
  const sources = answerSources(turnWithAnnotations([citation, citation]));

  assert.equal(sources.length, 1);
  assert.equal(sources[0]?.title, "Access Policy");
  assert.equal(sources[0]?.url, "https://kb/e1");
});

test("keeps citations in content order", () => {
  const sources = answerSources(turnWithAnnotations([
    annotation({ id: "first", title: "Decision Memo" }),
    annotation({ id: "second", title: "Background" }),
  ]));

  assert.deepEqual(sources.map((source) => source.id), ["first", "second"]);
});

test("a restricted citation is listed but never linked", () => {
  const [source] = answerSources(turnWithAnnotations([
    annotation({ id: "secret", title: "Board Pack", uri: "https://kb/secret", restricted: true }),
  ]));

  assert.equal(source?.restricted, true);
  assert.equal(source?.url, undefined);
});

test("page and section become one locator", () => {
  const [source] = answerSources(turnWithAnnotations([
    annotation({ id: "source", page: 12, section: "Controls" }),
  ]));

  assert.equal(source?.locator, "Controls · p. 12");
});

test("non-citation annotations are ignored", () => {
  assert.deepEqual(answerSources(turnWithAnnotations([{ type: "file_path", path: "/tmp/a" }])), []);
});

test("the summary counts cited sources", () => {
  assert.equal(sourcesLabel(answerSources(turnWithAnnotations([annotation({ id: "a" })]))), "1 source");
  assert.equal(
    sourcesLabel(answerSources(turnWithAnnotations([annotation({ id: "a" }), annotation({ id: "b" })]))),
    "2 sources",
  );
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
