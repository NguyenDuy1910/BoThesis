"use client";

import { ExternalLink, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { getKnowledgeItemViewer } from "../api";
import { resolveHighlightRange } from "../highlight";
import type { KnowledgeItemViewer, ViewerElement } from "../types";

export function DocumentViewer({ itemId }: { itemId: string }) {
  const [chunkId, setChunkId] = useState<string>();
  const [viewer, setViewer] = useState<KnowledgeItemViewer>();
  const [error, setError] = useState<string>();
  const elementRefs = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("chunk");
    setChunkId(value || undefined);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    void getKnowledgeItemViewer(itemId, chunkId, controller.signal)
      .then(setViewer)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Could not open this document.");
        }
      });
    return () => controller.abort();
  }, [chunkId, itemId]);

  useEffect(() => {
    const elementId = viewer ? resolveTargetElement(viewer) : undefined;
    if (!elementId) return;
    const target = elementRefs.current.get(elementId);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [viewer]);

  const targetElement = viewer ? resolveTargetElement(viewer) : undefined;

  const focusedRanges = useMemo(() => {
    const ranges = new Map<string, { start: number; end: number }[]>();
    if (!viewer?.focus) return undefined;
    for (const span of viewer.focus.citation.spans) {
      const element = viewer.elements.find((candidate) => candidate.element_id === span.element_id);
      if (!element) continue;
      const range = resolveHighlightRange(element.text, viewer.focus, span);
      if (range) ranges.set(element.element_id, [...(ranges.get(element.element_id) ?? []), range]);
    }
    if (!ranges.size && viewer.focus.citation.spans.length === 1) {
      const span = viewer.focus.citation.spans[0];
      const element = viewer.elements.find((candidate) => candidate.element_id === span?.element_id);
      if (element) {
        const range = resolveHighlightRange(element.text, viewer.focus);
        if (range) ranges.set(element.element_id, [range]);
      }
    }
    return ranges;
  }, [viewer]);

  if (error) return <div className="document-viewer__error" role="alert">{error}</div>;
  if (!viewer) {
    return (
      <div className="document-viewer__loading" role="status">
        <LoaderCircle aria-hidden="true" className="document-viewer__spinner" size={16} />
        Loading document…
      </div>
    );
  }

  return (
    <main className="document-viewer">
      <header className="document-viewer__header">
        <div>
          <p className="document-viewer__eyebrow">Bothesis document viewer</p>
          <h1>{viewer.title}</h1>
          {viewer.focus?.citation.spans[0]?.page && <p>Page {viewer.focus.citation.spans[0].page}{viewer.focus.citation.section ? ` · ${viewer.focus.citation.section}` : ""}</p>}
        </div>
        {(viewer.external_url || viewer.document_url) && (
          <a href={viewer.external_url || viewer.document_url || undefined} rel="noopener noreferrer" target="_blank">
            Open original <ExternalLink aria-hidden="true" size={13} />
          </a>
        )}
      </header>
      <section aria-label="Document content" className="document-viewer__content">
        {viewer.elements.map((element) => (
          <ViewerElementBlock
            element={element}
            focusedRanges={focusedRanges?.get(element.element_id)}
            visualFocused={targetElement === element.element_id && !focusedRanges?.get(element.element_id)?.length}
            key={element.element_id}
            register={(node) => {
              if (node) elementRefs.current.set(element.element_id, node);
              else elementRefs.current.delete(element.element_id);
            }}
          />
        ))}
      </section>
    </main>
  );
}

function ViewerElementBlock({
  element,
  focusedRanges,
  visualFocused,
  register,
}: {
  element: ViewerElement;
  focusedRanges?: { start: number; end: number }[];
  visualFocused?: boolean;
  register: (node: HTMLElement | null) => void;
}) {
  const text = element.text;
  const ranges = (focusedRanges ?? [])
    .map((range) => ({
      start: Math.max(0, Math.min(text.length, range.start)),
      end: Math.max(0, Math.min(text.length, range.end)),
    }))
    .filter((range) => range.end > range.start)
    .sort((left, right) => left.start - right.start);
  const content = ranges.length
    ? ranges.reduce<ReactNode[]>((parts, range, index) => {
      const previousEnd = index === 0 ? 0 : ranges[index - 1].end;
      parts.push(text.slice(previousEnd, range.start));
      parts.push(<mark className="document-viewer__highlight" key={`${range.start}-${range.end}`}>{text.slice(range.start, range.end)}</mark>);
      if (index === ranges.length - 1) parts.push(text.slice(range.end));
      return parts;
    }, [])
    : text;
  return (
    <article
      className={ranges.length || visualFocused ? "document-viewer__element document-viewer__element--focused" : "document-viewer__element"}
      data-element-id={element.element_id}
      id={element.anchor || undefined}
      ref={register}
    >
      {element.section_path.length > 0 && (
        <p className="document-viewer__section">{element.section_path.join(" / ")}</p>
      )}
      <p className="document-viewer__text">
        {content}
      </p>
    </article>
  );
}

function resolveTargetElement(viewer: KnowledgeItemViewer): string | undefined {
  const citation = viewer.focus?.citation;
  if (!citation) return undefined;
  const byId = citation.spans.find((span) => span.element_id)?.element_id;
  if (byId && viewer.elements.some((element) => element.element_id === byId)) return byId;
  if (citation.spans.some((span) => span.page !== null && span.page !== undefined)) {
    const page = citation.spans.find((span) => span.page !== null && span.page !== undefined)?.page;
    const pageElement = viewer.elements.find((element) => element.page === page);
    if (pageElement) return pageElement.element_id;
  }
  if (citation.anchor) {
    const anchorElement = viewer.elements.find((element) => element.anchor === citation.anchor);
    if (anchorElement) return anchorElement.element_id;
  }
  if (citation.section_path.length) {
    const sectionElement = viewer.elements.find((element) =>
      citation.section_path.every((part, index) => element.section_path[index] === part),
    );
    if (sectionElement) return sectionElement.element_id;
  }
  return viewer.elements[0]?.element_id;
}
