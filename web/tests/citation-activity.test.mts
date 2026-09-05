import assert from "node:assert/strict";
import test from "node:test";

import {
  isSameActivity,
  knowledgeDocumentActivity,
} from "../src/modules/chat/activity.ts";
import {
  adjacentPage,
  citationPages,
  citationRegions,
  citationTarget,
  pagesToPrefetch,
  previewPage,
  previewPages,
  regionStyle,
} from "../src/modules/knowledge/preview.ts";
import type { AnswerSource } from "../src/modules/chat/sources.ts";
import type {
  KnowledgePreview,
  PreviewAsset,
  ViewerCitation,
} from "../src/modules/knowledge/types.ts";

function source(overrides: Partial<AnswerSource> = {}): AnswerSource {
  return {
    id: "source-a1b2c3d4",
    index: 1,
    title: "Lesson 3.pdf",
    itemId: "item-1",
    chunkId: "item-1:12",
    internalUrl: "/knowledge/items/item-1?chunk=item-1%3A12",
    used: true,
    spans: [],
    ...overrides,
  };
}

function preview(pages: number[], overrides: Partial<KnowledgePreview> = {}): KnowledgePreview {
  const assets: PreviewAsset[] = pages.map((page) => ({
    url: `https://storage.test/signed/page-${page}.webp`,
    content_type: "image/webp",
    size_bytes: 1024,
    width: 1240,
    height: 1754,
    page,
  }));
  return {
    representation: "pages",
    original: {
      url: "https://storage.test/signed/original.pdf",
      file_name: "Lesson 3.pdf",
      content_type: "application/pdf",
      size_bytes: 4096,
    },
    assets,
    page_count: pages.length,
    truncated: false,
    coordinate_space: "normalized_top_left",
    ...overrides,
  };
}

function citation(overrides: Partial<ViewerCitation> = {}): ViewerCitation {
  return { section_path: [], spans: [], ...overrides };
}

// --- citation -> activity state -------------------------------------------

test("a citation becomes a knowledge document activity without copying the source", () => {
  const activity = knowledgeDocumentActivity(source({ page: 7 }));

  assert.deepEqual(activity, {
    type: "knowledge_document",
    citationId: "source-a1b2c3d4",
    itemId: "item-1",
    chunkId: "item-1:12",
    title: "Lesson 3.pdf",
    page: 7,
  });
});

test("re-clicking the open citation is a no-op, another citation replaces it", () => {
  const open = knowledgeDocumentActivity(source({ page: 3 }));

  assert.equal(isSameActivity(open, knowledgeDocumentActivity(source({ page: 3 }))), true);
  assert.equal(isSameActivity(null, open), false);
  // Another citation in the same document is a different activity.
  assert.equal(
    isSameActivity(
      open,
      knowledgeDocumentActivity(source({ id: "source-99", chunkId: "item-1:40", page: 8 })),
    ),
    false,
  );
});

test("an inline chip opens the panel at the cited page of the right document", () => {
  // The chip click path: the answer's citation carries only identity plus the
  // cited page, and the panel re-resolves the document from that.
  const activity = knowledgeDocumentActivity(source({
    id: "ref_1",
    index: 1,
    itemId: "item-7",
    chunkId: "item-7:31",
    page: 7,
  }));

  assert.equal(activity.type, "knowledge_document");
  assert.equal(activity.itemId, "item-7");
  assert.equal(activity.page, 7);
  // Nothing about the preview is copied into activity state.
  assert.equal("preview" in activity, false);
  assert.equal("spans" in activity, false);
});

test("clicking a second chip in the same document switches page in place", () => {
  const first = knowledgeDocumentActivity(source({ id: "ref_1", chunkId: "d:1", page: 3 }));
  const second = knowledgeDocumentActivity(source({ id: "ref_2", chunkId: "d:9", page: 8 }));

  assert.equal(isSameActivity(first, second), false);
  assert.equal(first.itemId, second.itemId);
  assert.equal(second.page, 8);
});

// --- citation -> page ------------------------------------------------------

test("span pages win, and a chunk page range is used when spans carry none", () => {
  assert.deepEqual(
    citationPages(citation({ spans: [{ page: 4 }, { page: 2 }, { page: 4 }] })),
    [2, 4],
  );
  assert.deepEqual(citationPages(citation({ page_start: 6, page_end: 8 })), [6, 7, 8]);
  assert.deepEqual(citationPages(citation()), []);
});

test("preview pages are resolved by number, never by asset position", () => {
  const rendered = preview([3, 1, 2]);

  assert.deepEqual(previewPages(rendered), [1, 2, 3]);
  assert.equal(previewPage(rendered, 3)?.url, "https://storage.test/signed/page-3.webp");
  assert.equal(previewPage(rendered, 9), undefined);
  assert.equal(previewPage(preview([1], { representation: "original", assets: [] }), 1), undefined);
});

test("paging walks only the rendered pages and stops at the ends", () => {
  const rendered = preview([1, 2, 3]);

  assert.equal(adjacentPage(rendered, 1, -1), undefined);
  assert.equal(adjacentPage(rendered, 1, 1), 2);
  assert.equal(adjacentPage(rendered, 3, 1), undefined);
  // Only the neighbours are warmed, never the whole document.
  assert.deepEqual(pagesToPrefetch(rendered, 2), [1, 3]);
  assert.deepEqual(pagesToPrefetch(rendered, 1), [2]);
});

// --- citation -> regions ---------------------------------------------------

test("every region of the cited page is highlighted, and other pages are not", () => {
  const rendered = preview([1, 2]);
  const cited = citation({
    spans: [
      { page: 2, bounding_box: { x: 0.1, y: 0.2, width: 0.5, height: 0.05 } },
      { page: 2, bounding_box: { x: 0.1, y: 0.3, width: 0.4, height: 0.05 } },
      { page: 1, bounding_box: { x: 0.1, y: 0.9, width: 0.4, height: 0.05 } },
    ],
  });

  const regions = citationRegions(cited, 2, rendered);

  assert.equal(regions.length, 2);
  assert.deepEqual(regions.map((region) => region.y), [0.2, 0.3]);
});

test("identical regions are painted once", () => {
  const box = { x: 0.1, y: 0.2, width: 0.5, height: 0.05 };
  const regions = citationRegions(
    citation({ spans: [{ page: 1, bounding_box: box }, { page: 1, bounding_box: box }] }),
    1,
    preview([1]),
  );

  assert.equal(regions.length, 1);
});

test("only the cited chunk's own spans are highlighted on the page", () => {
  // A page footer or page-number element belongs to the page, not to this
  // chunk, so it has no span here and must stay unhighlighted.
  const cited = citation({
    spans: [{ page: 7, bounding_box: { x: 0.1, y: 0.2, width: 0.6, height: 0.06 } }],
  });

  const regions = citationRegions(cited, 7, preview([7]));

  assert.equal(regions.length, 1);
  assert.deepEqual(regions[0], { x: 0.1, y: 0.2, width: 0.6, height: 0.06 });
});

test("an unrecognized coordinate space paints no highlight", () => {
  const regions = citationRegions(
    citation({ spans: [{ page: 1, bounding_box: { x: 0.1, y: 0.2, width: 0.5, height: 0.05 } }] }),
    1,
    preview([1], { coordinate_space: "pdf_points" as never }),
  );

  assert.deepEqual(regions, []);
});

test("normalized boxes map onto the rendered page as clamped percentages", () => {
  assert.deepEqual(regionStyle({ x: 0.25, y: 0.5, width: 0.5, height: 0.1 }), {
    left: "25%",
    top: "50%",
    width: "50%",
    height: "10%",
  });
  assert.deepEqual(regionStyle({ x: -0.2, y: 1.4, width: 2, height: 0.1 }), {
    left: "0%",
    top: "100%",
    width: "100%",
    height: "10%",
  });
});

// --- fallback ladder -------------------------------------------------------

test("citation precision degrades instead of fabricating a location", () => {
  const rendered = preview([1, 2]);
  const withBox = citation({
    spans: [{ page: 2, bounding_box: { x: 0.1, y: 0.2, width: 0.5, height: 0.05 } }],
  });

  assert.deepEqual(citationTarget(withBox, rendered), { precision: "region", page: 2 });
  // A page but no coordinates: open the page, do not invent a highlight.
  assert.deepEqual(
    citationTarget(citation({ spans: [{ page: 2 }] }), rendered),
    { precision: "page", page: 2 },
  );
  // No page metadata at all, and no fallback page.
  assert.deepEqual(citationTarget(citation(), rendered), { precision: "document" });
  // A page the preview never rendered is not shown as a page citation.
  assert.deepEqual(
    citationTarget(citation({ spans: [{ page: 9 }] }), rendered),
    { precision: "document" },
  );
  // The page carried by the answer's citation is used when the chunk has none.
  assert.deepEqual(citationTarget(citation(), rendered, 1), { precision: "page", page: 1 });
  // A source with no rendered pages at all.
  assert.deepEqual(citationTarget(withBox, null), { precision: "document" });
});
