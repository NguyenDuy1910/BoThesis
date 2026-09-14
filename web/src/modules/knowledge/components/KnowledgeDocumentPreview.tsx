"use client";

import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  FileWarning,
  LoaderCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useClipboard } from "@/lib/hooks/useClipboard";
import { getKnowledgeItemViewer, KnowledgeViewerRequestError } from "../api";
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
  onAskSource,
  page: citedPage,
}: {
  chunkId: string;
  itemId: string;
  onAskSource?: (title: string) => void;
  page?: number;
}) {
  const [viewer, setViewer] = useState<KnowledgeItemViewer>();
  const [error, setError] = useState<SourceViewerFailure>();
  const [page, setPage] = useState<number>();
  // A page that has not painted yet must not carry a highlight over blank space.
  const [renderedPage, setRenderedPage] = useState<number>();
  const [pageError, setPageError] = useState<number>();
  // Preview URLs are short-lived. A page that fails to load is retried once
  // against freshly signed URLs before it is reported as unavailable.
  const [refresh, setRefresh] = useState(0);
  const refreshedRef = useRef(false);
  const requestRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    // A newer citation must win even if an earlier document resolves later.
    const request = (requestRef.current += 1);
    refreshedRef.current = false;
    setViewer(undefined);
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
        setError(sourceViewerFailure(cause));
      });
    return () => controller.abort();
  }, [chunkId, citedPage, itemId, refresh]);

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

  const onPageLoadFailed = useCallback((failed: number | undefined) => {
    if (refreshedRef.current) {
      setPageError(failed);
      return;
    }
    refreshedRef.current = true;
    setRefresh((value) => value + 1);
  }, []);

  // Keep a neighbour each way warm so paging feels immediate, without pulling
  // a long document across the network.
  const prefetch = page === undefined ? [] : pagesToPrefetch(preview, page);

  const retry = useCallback(() => {
    refreshedRef.current = false;
    setError(undefined);
    setRefresh((value) => value + 1);
  }, []);

  if (error) {
    return error.kind === "permission_denied" ? (
      <PreviewNotice
        icon="warning"
        title="You can’t open this source"
        detail="You can continue using the grounded answer, but your account cannot open the underlying source."
      />
    ) : (
      <PreviewNotice
        icon="warning"
        title="Source temporarily unavailable"
        detail="The grounded answer remains visible, but the original document could not be loaded. BoThesis will not reconstruct missing source text."
        onRetry={retry}
      />
    );
  }
  if (!viewer) return <PreviewNotice icon="spinner" title="Opening source…" />;

  return (
    <div className="source-preview">
      <SourceIdentity onAskSource={onAskSource} viewer={viewer} />
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
              onError={() => onPageLoadFailed(page)}
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
        ) : isHtmlSource(viewer) ? (
          <HtmlSourcePreview viewer={viewer} />
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
      {!viewer.focus?.chunk_text && (
        <p className="source-preview__no-excerpt">
          This answer is grounded in the document, but no exact passage maps cleanly to this statement.
        </p>
      )}
    </div>
  );
}

function SourceIdentity({
  onAskSource,
  viewer,
}: {
  onAskSource?: (title: string) => void;
  viewer: KnowledgeItemViewer;
}) {
  const { copy, copied } = useClipboard();
  const originalUrl = viewer.external_url || viewer.document_url || viewer.preview?.original.url;
  const page = viewer.focus?.citation.page_start;
  const sourceType = viewer.content_type.split(";", 1)[0]?.trim() || "Document";

  return (
    <section className="source-preview__identity" aria-label="Source details">
      <div className="source-preview__identity-heading">
        <span className="source-preview__identity-icon"><FileText aria-hidden="true" size={17} /></span>
        <div>
          <h3 title={viewer.title}>{viewer.title}</h3>
          <p>{sourceType}</p>
        </div>
      </div>
      <dl className="source-preview__facts">
        <div><dt>Access</dt><dd>Authorized</dd></div>
        {page && <div><dt>Page</dt><dd>{page}</dd></div>}
        {viewer.focus?.citation.section && <div><dt>Section</dt><dd>{viewer.focus.citation.section}</dd></div>}
      </dl>
      <div className="source-preview__actions">
        {originalUrl && (
          <a className="source-preview__action source-preview__action--contextual" href={originalUrl} rel="noopener noreferrer" target="_blank">
            <ExternalLink aria-hidden="true" size={13} />Open original
          </a>
        )}
        {onAskSource && (
          <button className="source-preview__action source-preview__action--soft" onClick={() => onAskSource(viewer.title)} type="button">
            Ask this document
          </button>
        )}
        {viewer.focus?.chunk_text && (
          <button className="source-preview__action source-preview__action--ghost" onClick={() => void copy(viewer.focus!.chunk_text)} type="button">
            {copied ? <Check aria-hidden="true" size={13} /> : <Copy aria-hidden="true" size={13} />}
            {copied ? "Copied" : "Copy quote"}
          </button>
        )}
      </div>
    </section>
  );
}

/** Render an HTML source without granting it access to the chat application. */
function HtmlSourcePreview({ viewer }: { viewer: KnowledgeItemViewer }) {
  const sourceUrl = viewer.preview?.original.url || viewer.document_url;
  if (!sourceUrl) return <UnrenderedSource viewer={viewer} />;
  return (
    <div className="source-preview__html">
      <p className="source-preview__html-note">
        Rendered source preview in an isolated sandbox.
      </p>
      <iframe
        className="source-preview__html-frame"
        referrerPolicy="no-referrer"
        sandbox="allow-scripts"
        src={sourceUrl}
        title={`${viewer.title} preview`}
      />
    </div>
  );
}

function isHtmlSource(viewer: KnowledgeItemViewer): boolean {
  const contentType = viewer.content_type.split(";", 1)[0]?.trim().toLowerCase();
  return contentType === "text/html" || /\.(?:html?|xhtml)$/i.test(viewer.title);
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
  onRetry,
  title,
}: {
  detail?: string;
  icon: "spinner" | "warning";
  link?: { href: string; label: string };
  onRetry?: () => void;
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
      {onRetry && <button className="source-preview__notice-retry" onClick={onRetry} type="button">Retry source</button>}
    </div>
  );
}

type SourceViewerFailure = {
  kind: "permission_denied" | "unavailable";
};

function sourceViewerFailure(cause: unknown): SourceViewerFailure {
  if (cause instanceof KnowledgeViewerRequestError && (cause.status === 401 || cause.status === 403)) {
    return { kind: "permission_denied" };
  }
  return { kind: "unavailable" };
}
