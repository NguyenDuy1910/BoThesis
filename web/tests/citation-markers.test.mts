import assert from "node:assert/strict";
import test from "node:test";

import {
  CITATION_ELEMENT,
  CITATION_NUMBER_PROPERTY,
  citationRenderingSources,
  rehypeCitationMarkers,
  splitCitationMarkers,
} from "../src/modules/chat/citation-markers.ts";
import type { AnswerSource } from "../src/modules/chat/sources.ts";

function text(value: string) {
  return { type: "text", value };
}

function element(tagName: string, children: unknown[]) {
  return { type: "element", tagName, properties: {}, children };
}

// --- marker splitting -----------------------------------------------------

test("a claim keeps its citation where the model placed it", () => {
  assert.deepEqual(
    splitCitationMarkers("You must create one VPC endpoint for each name. [1] Next."),
    [
      { type: "text", value: "You must create one VPC endpoint for each name. " },
      { type: "citation", number: 1, value: "[1]" },
      { type: "text", value: " Next." },
    ],
  );
});

test("one claim can carry several citations", () => {
  assert.deepEqual(
    splitCitationMarkers("Both apply. [1][2]").filter((s) => s.type === "citation"),
    [
      { type: "citation", number: 1, value: "[1]" },
      { type: "citation", number: 2, value: "[2]" },
    ],
  );
});

test("a repeated citation is split at every occurrence", () => {
  const numbers = splitCitationMarkers("First. [1] Second. [1]")
    .filter((segment) => segment.type === "citation")
    .map((segment) => (segment.type === "citation" ? segment.number : 0));

  assert.deepEqual(numbers, [1, 1]);
});

test("text without a marker is returned unchanged as one run", () => {
  assert.deepEqual(splitCitationMarkers("A plain answer."), [
    { type: "text", value: "A plain answer." },
  ]);
  // An array index is not a citation marker shape.
  assert.deepEqual(splitCitationMarkers("items[i]"), [{ type: "text", value: "items[i]" }]);
});

// --- rehype placement -----------------------------------------------------

test("markers become citation elements inside the block that holds them", () => {
  const tree = element("root", [
    element("p", [text("A claim. [1] More.")]),
  ]);

  rehypeCitationMarkers()(tree as never);

  const paragraph = (tree.children[0] as ReturnType<typeof element>);
  assert.equal(paragraph.children.length, 3);
  const chip = paragraph.children[1] as {
    tagName: string;
    properties: Record<string, string>;
    children: Array<{ value: string }>;
  };
  assert.equal(chip.tagName, CITATION_ELEMENT);
  assert.equal(chip.properties[CITATION_NUMBER_PROPERTY], "1");
  // The literal text is retained so an unresolved number can fall back to it.
  assert.equal(chip.children[0].value, "[1]");
});

test("code and links keep their literal brackets", () => {
  const tree = element("root", [
    element("pre", [element("code", [text("array[1]")])]),
    element("a", [text("see [1]")]),
  ]);

  rehypeCitationMarkers()(tree as never);

  const code = (tree.children[0] as ReturnType<typeof element>)
    .children[0] as ReturnType<typeof element>;
  assert.equal(code.children.length, 1);
  assert.equal((code.children[0] as { value: string }).value, "array[1]");
  const link = tree.children[1] as ReturnType<typeof element>;
  assert.equal(link.children.length, 1);
});

test("nested inline formatting still gets its chip", () => {
  const tree = element("root", [
    element("p", [element("strong", [text("Bold claim. [2]")])]),
  ]);

  rehypeCitationMarkers()(tree as never);

  const strong = (tree.children[0] as ReturnType<typeof element>)
    .children[0] as ReturnType<typeof element>;
  assert.equal(strong.children.length, 2);
  assert.equal((strong.children[1] as { tagName: string }).tagName, CITATION_ELEMENT);
});

// --- resolution -----------------------------------------------------------

test("only the answer's own citation numbers resolve to a chip", () => {
  const source: AnswerSource = {
    id: "ref_1",
    index: 1,
    title: "Lesson 3.pdf",
    itemId: "item-1",
    chunkId: "item-1:12",
    internalUrl: "/knowledge/items/item-1?chunk=item-1%3A12",
    used: true,
    spans: [],
  };
  const resolved = citationRenderingSources([source]);

  assert.equal(resolved.get(1)?.itemId, "item-1");
  // A number the answer never cited must not become clickable.
  assert.equal(resolved.get(9), undefined);
});
