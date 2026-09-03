"use client";

import clsx from "clsx";
import { BookOpen, ChevronRight, ExternalLink } from "lucide-react";
import { memo } from "react";

import { answerSources, sourcesLabel, type AnswerSource } from "../sources";
import type { TurnState } from "../types";

/**
 * Citations attached to a finished answer.
 *
 * Grounding is only grounding if the reader can inspect it, so the numbered
 * markers stay visible and open the source beside the conversation. The full
 * list below them stays one quiet line until asked, so it never competes with
 * the answer above it.
 */
export const AnswerSources = memo(function AnswerSources({
  activeCitationId,
  onOpenSource,
  turn,
}: {
  activeCitationId?: string;
  onOpenSource?: (source: AnswerSource) => void;
  turn?: TurnState;
}) {
  const sources = answerSources(turn);
  if (!sources.length) return null;

  return (
    <div className="answer-citations">
      <ul className="answer-citations__markers">
        {sources.map((source) => (
          <li key={source.id}>
            <button
              aria-label={`Show source ${source.index}: ${source.title}`}
              aria-pressed={activeCitationId === source.id}
              className={clsx(
                "answer-citations__marker",
                activeCitationId === source.id && "answer-citations__marker--active",
              )}
              onClick={() => onOpenSource?.(source)}
              title={[source.title, source.locator].filter(Boolean).join(" · ")}
              type="button"
            >
              {source.index}
            </button>
          </li>
        ))}
      </ul>

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
