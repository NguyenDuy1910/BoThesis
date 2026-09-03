"use client";

import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileWarning,
  LoaderCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getKnowledgeItemViewer } from "../api";
import {
  adjacentPage,
  citationRegions,
  citationTarget,
  pagesToPrefetch,
  previewPage,
  previewPages,
  regionStyle,
} from "../preview";
import type { KnowledgeItemViewer } from "../types";

/**
 * A cited source, shown as its rendered pages beside the conversation.
 *
 * The pages come from the previews ingestion already produced, so opening a
 * citation never re-renders a PDF and never asks the browser to understand
 * where those objects live.
 */
export function KnowledgeDocumentPreview({
  chunkId,
  itemId,
  page: citedPage,
}: {
  chunkId: string;
  itemId: string;
  page?: number;
}) {
  const [viewer, setViewer] = useState<KnowledgeItemViewer>();
  const [error, setError] = useState<string>();
  const [page, setPage] = useState<number>();
  // A page that has not painted yet must not carry a highlight over blank space.
  const [renderedPage, setRenderedPage] = useState<number>();
  const [pageError, setPageError] = useState<number>();
  const requestRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    // A newer citation must win even if an earlier document resolves later.
    const request = (requestRef.current += 1);
    setError(undefined);
    setPageError(undefined);
    void getKnowledgeItemViewer(itemId, chunkId, controller.signal)
      .then((resolved) => {
        if (requestRef.current !== request) return;
        setViewer(resolved);
        setPage(citationTarget(resolved.focus?.citation, resolved.preview, citedPage).page
          ?? previewPages(resolved.preview)[0]);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || requestRef.current !== request) return;
        setError(cause instanceof Error ? cause.message : "Could not open this source.");
      });
    return () => controller.abort();
  }, [chunkId, citedPage, itemId]);

  const preview = viewer?.preview;
  const asset = page === undefined ? undefined : previewPage(preview, page);
  const regions = useMemo(
    () => citationRegions(viewer?.focus?.citation, page, preview),
    [page, preview, viewer],
  );
  const pages = useMemo(() => previewPages(preview), [preview]);
  const previousPage = page === undefined ? undefined : adjacentPage(preview, page, -1);
  const nextPage = page === undefined ? undefined : adjacentPage(preview, page, 1);

  const goTo = useCallback((target: number | undefined) => {
    if (target === undefined) return;
    setPageError(undefined);
    setPage(target);
  }, []);

  // Keep a neighbour each way warm so paging feels immediate, without pulling
  // a long document across the network.
  const prefetch = page === undefined ? [] : pagesToPrefetch(preview, page);

  if (error) {
    return <PreviewNotice icon="warning" title="This source is unavailable" detail={error} />;
  }
  if (!viewer) return <PreviewNotice icon="spinner" title="Opening source…" />;

  return (
    <div className="source-preview">
      <div className="source-preview__meta">
        {viewer.focus?.citation.section && (
          <span className="source-preview__section">{viewer.focus.citation.section}</span>
        )}
        {pages.length > 0 && page !== undefined && (
          <span className="source-preview__pager">
            <button
              aria-label="Previous page"
              className="source-preview__page-button"
              disabled={previousPage === undefined}
              onClick={() => goTo(previousPage)}
              type="button"
            >
              <ChevronLeft aria-hidden="true" size={14} />
            </button>
            <span className="source-preview__page-count">
              Page {page}
              {viewer.preview?.page_count ? ` / ${viewer.preview.page_count}` : ""}
            </span>
            <button
              aria-label="Next page"
              className="source-preview__page-button"
              disabled={nextPage === undefined}
              onClick={() => goTo(nextPage)}
              type="button"
            >
              <ChevronRight aria-hidden="true" size={14} />
            </button>
          </span>
        )}
      </div>

      <div className="source-preview__stage">
        {asset ? (
          <div
            className="source-preview__page"
            style={{ aspectRatio: `${asset.width} / ${asset.height}` }}
          >
            <img
              alt={`${viewer.title}, page ${page}`}
              className="source-preview__image"
              // Keyed by page, not by URL: moving to another page remounts so a
              // slow image cannot paint over a newer one, while a refreshed URL
              // for the page on screen swaps in without blanking it.
              key={page}
              onError={() => setPageError(page)}
              onLoad={() => setRenderedPage(page)}
              src={asset.url}
            />
            {renderedPage !== page && !pageError && (
              <span className="source-preview__page-loading" role="status">
                <LoaderCircle aria-hidden="true" className="source-preview__spinner" size={16} />
              </span>
            )}
            {pageError === page && (
              <span className="source-preview__page-loading" role="alert">
                This page could not be loaded.
              </span>
            )}
            {renderedPage === page
              && regions.map((region) => (
                <span
                  aria-hidden="true"
                  className="source-preview__highlight"
                  key={`${region.x}:${region.y}:${region.width}:${region.height}`}
                  style={regionStyle(region)}
                />
              ))}
          </div>
        ) : (
          <UnrenderedSource viewer={viewer} />
        )}
        {prefetch.map((target) => {
          const upcoming = previewPage(preview, target);
          return upcoming ? (
            <img alt="" aria-hidden="true" className="source-preview__prefetch" key={upcoming.url} src={upcoming.url} />
          ) : null;
        })}
      </div>

      {viewer.focus?.chunk_text && (
        <blockquote className="source-preview__quote">{viewer.focus.chunk_text}</blockquote>
      )}
    </div>
  );
}

/** Every reason a page image is not available, told apart honestly. */
function UnrenderedSource({ viewer }: { viewer: KnowledgeItemViewer }) {
  if (viewer.status === "pending" || viewer.status === "processing") {
    return (
      <PreviewNotice
        icon="spinner"
        title="Preview is still being prepared"
        detail="This source has been indexed. Its page previews are still rendering."
      />
    );
  }
  if (viewer.status === "deleted") {
    return <PreviewNotice icon="warning" title="This source has been removed" />;
  }
  return (
    <PreviewNotice
      icon="warning"
      title="No page preview for this source"
      detail={
        viewer.focus?.citation.section
          ? `The citation points at “${viewer.focus.citation.section}”.`
          : "The cited text is shown below."
      }
      link={
        viewer.external_url || viewer.document_url
          ? { href: viewer.external_url || viewer.document_url!, label: "Open original" }
          : undefined
      }
    />
  );
}

function PreviewNotice({
  detail,
  icon,
  link,
  title,
}: {
  detail?: string;
  icon: "spinner" | "warning";
  link?: { href: string; label: string };
  title: string;
}) {
  return (
    <div className="source-preview__notice" role={icon === "spinner" ? "status" : "alert"}>
      {icon === "spinner" ? (
        <LoaderCircle aria-hidden="true" className="source-preview__spinner" size={18} />
      ) : (
        <FileWarning aria-hidden="true" size={18} />
      )}
      <p className="source-preview__notice-title">{title}</p>
      {detail && <p className="source-preview__notice-detail">{detail}</p>}
      {link && (
        <a
          className="source-preview__notice-link"
          href={link.href}
          rel="noopener noreferrer"
          target="_blank"
        >
          {link.label} <ExternalLink aria-hidden="true" size={12} />
        </a>
      )}
    </div>
  );
}
