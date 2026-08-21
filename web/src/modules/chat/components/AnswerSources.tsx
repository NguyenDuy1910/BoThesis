"use client";

import { ChevronRight, ExternalLink, Lock } from "lucide-react";
import { memo } from "react";

import { answerSources, sourcesLabel } from "../sources";
import type { TurnState } from "../types";

/**
 * Citations attached to a finished answer, collapsed by default.
 *
 * Grounding is only grounding if the reader can inspect it, so this always
 * renders when the turn produced citations — but it stays one quiet line until
 * asked, so it never competes with the answer above it.
 */
export const AnswerSources = memo(function AnswerSources({
  turn,
}: {
  turn?: TurnState;
}) {
  const sources = answerSources(turn);
  if (!sources.length) return null;

  return (
    <details className="answer-sources">
      <summary>
        <ChevronRight aria-hidden="true" className="answer-sources__caret" size={13} />
        <span>{sourcesLabel(sources)}</span>
      </summary>
      <ul className="answer-sources__list">
        {sources.map((source) => (
          <li className="answer-sources__item" key={source.id}>
            {source.url ? (
              <a
                className="answer-sources__link"
                href={source.url}
                rel="noopener noreferrer"
                target="_blank"
              >
                <span className="answer-sources__title">{source.title}</span>
                <ExternalLink aria-hidden="true" size={11} />
              </a>
            ) : (
              <span className="answer-sources__title">
                {source.title}
                {source.restricted && (
                  <span className="answer-sources__restricted">
                    <Lock aria-hidden="true" size={10} />
                    Restricted
                  </span>
                )}
              </span>
            )}
            {(source.locator || source.origin) && (
              <span className="answer-sources__meta">
                {[source.origin, source.locator].filter(Boolean).join(" · ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
});
