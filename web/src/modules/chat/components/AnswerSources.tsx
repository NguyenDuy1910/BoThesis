"use client";

import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { memo } from "react";

import type { AnswerSource } from "../sources";
import { FileTypeIcon } from "./ResourceIcon";

/**
 * Compact source chips directly under a finished answer.
 *
 * Citations also render next to their claims in the prose. Keeping this quiet
 * secondary group visible means the supporting documents remain immediately
 * inspectable even when the model did not place an inline marker.
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
      <ul aria-label="Sources used in this answer" className="answer-sources answer-sources__list">
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
                <FileTypeIcon name={source.title} />
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
                  <ExternalLink aria-hidden="true" size={12} />
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
    </div>
  );
});
