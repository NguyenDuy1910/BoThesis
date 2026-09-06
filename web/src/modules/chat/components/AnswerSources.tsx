"use client";

import clsx from "clsx";
import { BookOpen, ChevronRight, ExternalLink } from "lucide-react";
import { memo } from "react";

import { sourcesLabel, type AnswerSource } from "../sources";

/**
 * The optional source summary under a finished answer.
 *
 * Citations themselves are inline, next to the claims they support. This stays
 * one quiet line until asked, so a reader who wants the whole provenance list
 * can open it without it competing with the answer above.
 */
export const AnswerSources = memo(function AnswerSources({
  activeCitationId,
  onOpenSource,
  sources,
}: {
  activeCitationId?: string;
  onOpenSource?: (source: AnswerSource) => void;
  sources: readonly AnswerSource[];
}) {
  if (!sources.length) return null;

  return (
    <div className="answer-citations">
      <details className="answer-sources">
        <summary>
          <ChevronRight aria-hidden="true" className="answer-sources__caret" size={13} />
          <span>{sourcesLabel(sources)}</span>
        </summary>
        <ul className="answer-sources__list">
          {sources.map((source) => (
            <li className="answer-sources__item" key={source.id}>
              <span className="answer-sources__actions">
                <button
                  className={clsx(
                    "answer-sources__link",
                    activeCitationId === source.id && "answer-sources__link--active",
                  )}
                  onClick={() => onOpenSource?.(source)}
                  type="button"
                >
                  <BookOpen aria-hidden="true" size={11} />
                  <span className="answer-sources__title">{source.title}</span>
                </button>
                {source.originalUrl && (
                  <a
                    aria-label={`Open original source for ${source.title}`}
                    className="answer-sources__external-link"
                    href={source.originalUrl}
                    rel="noopener noreferrer"
                    target="_blank"
                    title="Open original source"
                  >
                    <ExternalLink aria-hidden="true" size={11} />
                  </a>
                )}
              </span>
              {(source.locator || source.origin) && (
                <span className="answer-sources__meta">
                  {[source.origin, source.locator].filter(Boolean).join(" · ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
});
