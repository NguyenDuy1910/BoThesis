import type {
  KnowledgePreview,
  PreviewAsset,
  ViewerBoundingBox,
  ViewerCitation,
} from "./types";

/**
 * Where a citation can be shown, in decreasing precision.
 *
 * `region` highlights the exact cited geometry, `page` opens the right page
 * without inventing a highlight, and `document` is the honest fallback when
 * ingestion captured no location at all.
 */
export type CitationPrecision = "region" | "page" | "document";

export interface CitationTarget {
  precision: CitationPrecision;
  /** One-based, matching preview asset pages. */
  page?: number;
}

/**
 * Ingestion stores bounding boxes as fractions of the source page with a
 * top-left origin (see the connector's `_normalized_bbox`), and a preview page
 * is a uniformly scaled render of that same page. Fractions therefore map
 * directly onto the rendered image at any size, so a highlight stays aligned
 * through panel and browser resizing without measuring pixels.
 */
const SUPPORTED_COORDINATE_SPACE = "normalized_top_left";

/** The pages a citation refers to, in ascending order. */
export function citationPages(citation: ViewerCitation | undefined): number[] {
  if (!citation) return [];
  const pages = new Set<number>();
  for (const span of citation.spans) {
    if (typeof span.page === "number" && span.page >= 1) pages.add(span.page);
  }
  if (!pages.size) {
    const start = citation.page_start;
    const end = citation.page_end ?? start;
    if (typeof start === "number" && typeof end === "number") {
      for (let page = start; page <= end; page += 1) pages.add(page);
    }
  }
  return [...pages].sort((left, right) => left - right);
}

/** The regions of one page this citation covers, as page fractions. */
export function citationRegions(
  citation: ViewerCitation | undefined,
  page: number | undefined,
  preview: KnowledgePreview | undefined | null,
): ViewerBoundingBox[] {
  if (!citation || !preview || preview.coordinate_space !== SUPPORTED_COORDINATE_SPACE) {
    return [];
  }
  const regions: ViewerBoundingBox[] = [];
  for (const span of citation.spans) {
    const box = span.bounding_box;
    if (!box || !isPaintable(box)) continue;
    // A span without a page belongs to a single-page source; anything else
    // must match the page on screen so a highlight never lands on the wrong one.
    const spanPage = typeof span.page === "number" ? span.page : page;
    if (spanPage !== page) continue;
    if (!regions.some((existing) => isSameRegion(existing, box))) regions.push(box);
  }
  return regions;
}

/** Resolve where to open a citation, degrading rather than fabricating. */
export function citationTarget(
  citation: ViewerCitation | undefined,
  preview: KnowledgePreview | undefined | null,
  fallbackPage?: number,
): CitationTarget {
  const page = citationPages(citation)[0] ?? fallbackPage;
  if (page === undefined) return { precision: "document" };
  if (!previewPage(preview, page)) return { precision: "document" };
  return {
    precision: citationRegions(citation, page, preview).length ? "region" : "page",
    page,
  };
}

/** The rendered page asset, when this preview has one for that page. */
export function previewPage(
  preview: KnowledgePreview | undefined | null,
  page: number,
): PreviewAsset | undefined {
  if (!preview || preview.representation === "original") return undefined;
  return preview.assets.find((asset) => pageOf(asset) === page);
}

/** Every rendered page number this preview can show, in order. */
export function previewPages(preview: KnowledgePreview | undefined | null): number[] {
  if (!preview || preview.representation === "original") return [];
  return preview.assets
    .map(pageOf)
    .filter((page): page is number => page !== undefined)
    .sort((left, right) => left - right);
}

/** The page to show next, or `undefined` at the end of the rendered pages. */
export function adjacentPage(
  preview: KnowledgePreview | undefined | null,
  page: number,
  step: 1 | -1,
): number | undefined {
  const pages = previewPages(preview);
  const index = pages.indexOf(page);
  if (index < 0) return undefined;
  return pages[index + step];
}

/**
 * The pages worth holding in the browser cache around the one on screen.
 *
 * Only the cited page is required; a neighbour each way makes paging feel
 * immediate without pulling a long document across the network.
 */
export function pagesToPrefetch(
  preview: KnowledgePreview | undefined | null,
  page: number,
): number[] {
  return [adjacentPage(preview, page, -1), adjacentPage(preview, page, 1)]
    .filter((value): value is number => value !== undefined);
}

/** Position one region over the rendered page, as CSS percentages. */
export function regionStyle(box: ViewerBoundingBox): {
  left: string;
  top: string;
  width: string;
  height: string;
} {
  return {
    left: `${percentage(box.x)}%`,
    top: `${percentage(box.y)}%`,
    width: `${percentage(box.width)}%`,
    height: `${percentage(box.height)}%`,
  };
}

function pageOf(asset: PreviewAsset): number | undefined {
  return typeof asset.page === "number" && asset.page >= 1 ? asset.page : undefined;
}

function isPaintable(box: ViewerBoundingBox): boolean {
  return (
    Number.isFinite(box.x)
    && Number.isFinite(box.y)
    && box.width > 0
    && box.height > 0
  );
}

function isSameRegion(left: ViewerBoundingBox, right: ViewerBoundingBox): boolean {
  return (
    left.x === right.x
    && left.y === right.y
    && left.width === right.width
    && left.height === right.height
  );
}

function percentage(value: number): number {
  return Math.min(100, Math.max(0, value * 100));
}
